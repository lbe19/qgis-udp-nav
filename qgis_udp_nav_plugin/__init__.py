def classFactory(iface):
    from .plugin import QgisUdpNavPlugin

    return QgisUdpNavPlugin(iface)
