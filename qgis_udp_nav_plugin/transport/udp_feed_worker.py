from __future__ import annotations

import time
from typing import Optional, Tuple

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot
from qgis.PyQt.QtNetwork import QHostAddress, QUdpSocket

from ..model.feed_config import FeedConfig
from ..parser.core import split_datagram


def _fallback_any_ipv4_address() -> QHostAddress:
    special_enum = getattr(QHostAddress, "SpecialAddress", None)
    if special_enum is not None and hasattr(special_enum, "AnyIPv4"):
        return QHostAddress(special_enum.AnyIPv4)

    any_ipv4 = getattr(QHostAddress, "AnyIPv4", None)
    if any_ipv4 is not None:
        return QHostAddress(any_ipv4)

    any_address = getattr(QHostAddress, "Any", None)
    if any_address is not None:
        return QHostAddress(any_address)

    return QHostAddress("0.0.0.0")


def _bind_flags():
    bind_flag_enum = getattr(QUdpSocket, "BindFlag", None)
    if (
        bind_flag_enum is not None
        and hasattr(bind_flag_enum, "ShareAddress")
        and hasattr(bind_flag_enum, "ReuseAddressHint")
    ):
        return bind_flag_enum.ShareAddress | bind_flag_enum.ReuseAddressHint

    return QUdpSocket.ShareAddress | QUdpSocket.ReuseAddressHint


class UdpFeedWorker(QObject):
    """Receives UDP datagrams and emits raw sentences as strings.

    Parsing is intentionally NOT done here — PyQt6/Qt6 cannot reliably
    deliver custom Python objects across thread boundaries via signals.
    The controller parses sentences on the main thread instead.
    """

    sentence_received = pyqtSignal(str, str, str)  # feed_id, source_address, line
    status = pyqtSignal(str, str, str)  # feed_id, level, message
    stopped = pyqtSignal(str)  # feed_id

    def __init__(self, feed_config: FeedConfig) -> None:
        super().__init__()
        self._config = feed_config
        self._socket: Optional[QUdpSocket] = None
        self._stale_timer: Optional[QTimer] = None
        self._last_datagram_ts = 0.0
        self._stale_reported = False
        self._stopping = False

    _MAX_DATAGRAMS_PER_CYCLE = 200

    @pyqtSlot()
    def start(self) -> None:
        if self._socket is not None:
            return

        self._stopping = False

        self._socket = QUdpSocket(self)
        address = QHostAddress(self._config.bind_host)
        if address.isNull():
            address = _fallback_any_ipv4_address()
            self.status.emit(
                self._config.feed_id,
                "warning",
                f"Invalid bind address '{self._config.bind_host}', falling back to 0.0.0.0",
            )

        flags = _bind_flags()
        bind_ok = self._socket.bind(address, self._config.port, flags)
        if not bind_ok:
            message = self._socket.errorString() or "unknown socket error"
            self.status.emit(
                self._config.feed_id,
                "error",
                f"Unable to bind UDP socket on {self._config.bind_host}:{self._config.port}: {message}",
            )
            self._socket.close()
            self._socket.deleteLater()
            self._socket = None
            self.stopped.emit(self._config.feed_id)
            return

        self._socket.readyRead.connect(self._on_ready_read)
        self._last_datagram_ts = time.monotonic()

        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(1000)
        self._stale_timer.timeout.connect(self._check_stale)
        self._stale_timer.start()

        self.status.emit(
            self._config.feed_id,
            "info",
            f"Listening on UDP {self._config.bind_host}:{self._config.port}",
        )

    @pyqtSlot()
    def stop(self) -> None:
        self._stopping = True

        if self._stale_timer is not None:
            self._stale_timer.stop()
            self._stale_timer.deleteLater()
            self._stale_timer = None

        if self._socket is not None:
            try:
                self._socket.readyRead.disconnect(self._on_ready_read)
            except TypeError:
                pass
            self._socket.close()
            self._socket.deleteLater()
            self._socket = None

        self.status.emit(self._config.feed_id, "info", "Feed stopped")
        self.stopped.emit(self._config.feed_id)

    @pyqtSlot()
    def _on_ready_read(self) -> None:
        if self._socket is None or self._should_abort_processing():
            return

        processed = 0
        while self._socket is not None and self._socket.hasPendingDatagrams():
            if self._should_abort_processing():
                break

            payload, source_address = self._read_datagram()
            if payload is None:
                continue

            self._last_datagram_ts = time.monotonic()
            self._stale_reported = False

            text = payload.decode("ascii", errors="replace")
            lines = split_datagram(text)
            for line in lines:
                self.sentence_received.emit(self._config.feed_id, source_address, line)

            processed += 1
            if processed >= self._MAX_DATAGRAMS_PER_CYCLE:
                break

        if (
            self._socket is not None
            and self._socket.hasPendingDatagrams()
            and not self._should_abort_processing()
        ):
            QTimer.singleShot(0, self._on_ready_read)

    def _read_datagram(self) -> Tuple[Optional[bytes], str]:
        if self._socket is None:
            return None, ""

        if hasattr(self._socket, "receiveDatagram"):
            datagram = self._socket.receiveDatagram()
            sender = datagram.senderAddress().toString()
            return bytes(datagram.data()), sender

        size = self._socket.pendingDatagramSize()
        payload, host, _port = self._socket.readDatagram(size)
        sender = host.toString() if hasattr(host, "toString") else str(host)
        return bytes(payload), sender

    @pyqtSlot()
    def _check_stale(self) -> None:
        if self._should_abort_processing():
            return

        if self._stale_reported:
            return

        now = time.monotonic()
        age = now - self._last_datagram_ts
        if age >= max(1, self._config.stale_timeout_sec):
            self._stale_reported = True
            self.status.emit(
                self._config.feed_id,
                "warning",
                f"No datagrams received for {age:.1f}s",
            )

    def _should_abort_processing(self) -> bool:
        if self._stopping:
            return True

        thread = self.thread()
        if thread is not None and thread.isInterruptionRequested():
            return True
        return False
