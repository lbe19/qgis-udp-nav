# Lessons Learned: The Great Layer Invisibility Disaster (May 2026)

## What Happened

After opening a saved QGIS project, the polygon vessel layer was completely invisible. The overview arrow marker worked, but the main geographic-scale polygon — the entire point of the plugin — rendered nothing. This persisted across restarts, project reloads, and plugin reloads.

## Root Causes

### 1. `addMapLayer(layer, True)` Uses Deferred Tree Insertion

When you call `QgsProject.instance().addMapLayer(layer)` with `addToLegend=True` (the default), QGIS delegates tree node creation to the internal `QgsLayerTreeRegistryBridge`. This bridge **defers** the actual insertion into the layer tree via the Qt event loop.

**Consequence:** Immediately after `addMapLayer()`, calling `root.findLayer(layer.id())` returns `None` because the tree node doesn't exist yet. Any visibility checks, legend manipulation, or rendering order logic that runs synchronously after layer creation is a no-op.

### 2. Layer Rendering Order = Bottom of Tree Renders First

QGIS renders layers from **bottom to top** in the layer tree. The deferred bridge insertion placed our memory layers at unpredictable positions — often **below** the basemap tiles. The polygon was being rendered, but underneath everything else. Invisible.

### 3. Multiple Project Transitions Cause Layer Duplication

During QGIS startup with a saved project, **3-4 project transition signals** fire within 8 seconds:
- `readProject` (start)
- `projectRead` (completed)  
- Sometimes a second pair if the project references missing layers

Each transition triggered `reset_project_layer_caches()` → feed restart → new layer creation. But the old layers from 2 seconds ago were still in the project registry. Over multiple sessions, this accumulated **dozens** of orphaned memory layers in the project file (we found 412 references in a single .qgz).

### 4. Memory Layers Saved in Project Are Dead on Reload

QGIS saves memory layer *definitions* in the .qgs XML, but memory layers have no persistent backing store. On project reload they appear in the layer tree as broken/invalid entries (red/yellow icons). The plugin then creates **new** memory layers alongside the dead ones, compounding the clutter.

## The Fix

### Manual Tree Insertion at Position 0

```python
# DON'T do this:
QgsProject.instance().addMapLayer(layer)  # deferred, unpredictable position

# DO this:
QgsProject.instance().addMapLayer(layer, False)  # add to registry, NOT to legend
root = QgsProject.instance().layerTreeRoot()
root.insertChildNode(0, QgsLayerTreeLayer(layer))  # position 0 = top = renders LAST = on top

# Also handle custom layer order if the user has one set:
if root.hasCustomLayerOrder():
    order = root.customLayerOrder()
    if layer not in order:
        order.insert(0, layer)
        root.setCustomLayerOrder(order)
```

This gives you:
- **Immediate** tree node (no deferred async insertion)
- **Guaranteed** rendering on top of all other layers
- **Deterministic** behavior across project loads

### Orphan Cleanup Before Layer Creation

Before creating a new memory layer, always remove any existing layers with the same feed ID and kind:

```python
self._remove_project_layers_for_feed(feed.feed_id, layer_kind, expected_name)
```

This prevents accumulation across transitions.

### Deferred Canvas Refresh

QGIS's map canvas caching may not invalidate on the same event-loop tick a layer is created. A 200ms deferred `canvas.refresh()` after the first position update acts as a safety net:

```python
if self._position_count == 1:
    QTimer.singleShot(200, self._deferred_canvas_refresh)
```

### Project File Hygiene

Memory layers should **never** accumulate in the project file. The plugin marks its layers as ephemeral, but QGIS still saves them. The orphan cleanup on layer creation handles runtime, but if the project file gets polluted (like ours did — 3MB of garbage), you need to manually clean the XML:

```python
# Remove elements matching these patterns from the .qgs:
# - <layer-tree-layer> with id containing "UDP_Nav"
# - <legendlayer> with name containing "UDP Nav"  
# - <maplayer> with <layername> containing "UDP Nav"
# - <layer id="UDP_Nav_..."> in visibility presets
# - entries in <custom-order> referencing UDP_Nav layer IDs
```

## Rules Going Forward

1. **NEVER** use `addMapLayer(layer, True)` for plugin memory layers. Always `False` + manual tree insertion.
2. **ALWAYS** clean up orphaned layers before creating new ones.
3. **ALWAYS** call `layer.triggerRepaint()` after geometry changes — `updateExtents()` alone is not enough.
4. **NEVER** trust that `root.findLayer()` works immediately after `addMapLayer()`.
5. **Track layers go at the BOTTOM** of the tree (behind everything), live vessel/overview layers go at the TOP.
6. If the project file grows suspiciously large, inspect the XML for accumulated memory layer garbage.

## Key QGIS Documentation Quotes

> "If caching is enabled, a simple canvas refresh might not be sufficient to trigger a redraw and you must clear the cached image for the layer."  
> — QGIS PyQGIS Cookbook

> "Update layer's extent when new features have been added because change of extent in provider is not propagated to the layer."  
> — QGIS PyQGIS Cookbook (Memory Layers section)

## Timeline

| Date | Event |
|------|-------|
| May 28 | Polygon vessel layer stops rendering after project load |
| May 29 | Root cause identified: deferred tree insertion + layer ordering |
| May 29 | Fix implemented: manual `insertChildNode(0, ...)` + orphan cleanup |
| May 29 | Project file cleaned: 412 orphaned references removed |
| May 29 | Vessel rendering confirmed working |
