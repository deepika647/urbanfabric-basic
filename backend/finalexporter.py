"""
VectoMap Exporter v6
Fixes:
- 3D mode now always draws 2D building footprint outlines (BUILDINGS layer)
  in addition to the 3D extrusion — base plan and outlines are visible
- Roads use elevation=0.001 in 3D mode so they sit above the ground
  plane and are not hidden under building floor geometry
"""

import io
import osmnx as ox
import ezdxf
from shapely.ops import unary_union
from shapely.geometry import Polygon, MultiPolygon

ox.settings.timeout = 180

MAJOR_ROADS = {"motorway", "trunk", "primary", "secondary"}
FOOT_ROADS  = {"footway", "path", "cycleway", "steps", "pedestrian"}

DEFAULT_FLOOR_HEIGHT_M  = 3.5
DEFAULT_BUILDING_LEVELS = 3
MIN_BUILDING_HEIGHT_M   = 3.5


def get_polygons(geom):
    if geom is None: return []
    if isinstance(geom, Polygon): return [geom]
    if isinstance(geom, MultiPolygon): return list(geom.geoms)
    return []

def transform_xy(coords, min_x, min_y, scale):
    return [((x - min_x) / scale, (y - min_y) / scale) for x, y in coords]

def get_road_layer(hw):
    if isinstance(hw, list): hw = hw[0]
    if hw in MAJOR_ROADS: return "ROAD_MAJOR"
    if hw in FOOT_ROADS:  return "ROAD_FOOT"
    return "ROAD_MINOR"

def safe_float(v, fallback=None):
    try:
        return float(str(v).replace("m","").replace("M","").strip())
    except Exception:
        return fallback

def get_building_height(row, scale):
    h = safe_float(row.get("height"), None)
    if h and h > 0:
        return max(h, MIN_BUILDING_HEIGHT_M) / scale
    lvl = safe_float(row.get("building:levels"), None)
    if lvl and lvl > 0:
        return max(lvl * DEFAULT_FLOOR_HEIGHT_M, MIN_BUILDING_HEIGHT_M) / scale
    return (DEFAULT_BUILDING_LEVELS * DEFAULT_FLOOR_HEIGHT_M) / scale


def draw_2d_building(msp, coords_2d, layer, hatch_layer):
    """2D mode: border outline + SOLID hatch fill."""
    msp.add_lwpolyline(coords_2d, close=True, dxfattribs={"layer": layer})
    hatch = msp.add_hatch(color=254, dxfattribs={"layer": hatch_layer})
    hatch.paths.add_polyline_path([(x, y) for x, y in coords_2d], is_closed=True)
    hatch.set_pattern_fill("SOLID")


def draw_3d_building(msp, coords_2d, height_z, layer):
    """
    Two stacked LWPOLYLINE extrusions produce a fully closed solid box.
      A: elevation=0,       thickness=+h  -> walls + floor cap (AutoCAD fills bottom)
      B: elevation=h,       thickness=-h  -> walls + roof cap  (AutoCAD fills top)
    Negative thickness extrudes downward. Both share the same footprint —
    no doubling. This is the only way to get a filled roof without ACIS solids.
    """
    msp.add_lwpolyline(coords_2d, close=True, dxfattribs={
        "layer": layer, "elevation": 0, "thickness": height_z,
    })
    msp.add_lwpolyline(coords_2d, close=True, dxfattribs={
        "layer": layer, "elevation": height_z, "thickness": -height_z,
    })


def set_shaded_viewport(doc):
    try:
        active_vps = doc.viewports.get("*Active")
        if active_vps:
            entries = active_vps if isinstance(active_vps, list) else [active_vps]
            for vp in entries:
                vp.dxf.render_mode = 5   # Flat Shaded + Edges
    except Exception as e:
        print(f"  note: viewport shading not set ({e})")


def export_to_dxf_bytes(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    scale: int = 1000,
    include_buildings: bool = True,
    include_roads: bool = True,
    export_3d: bool = False,
) -> bytes:
    """Generate DXF and return as raw bytes. Nothing written to disk."""

    if abs(max_lat - min_lat) > 0.05 or abs(max_lon - min_lon) > 0.05:
        raise ValueError("Area too large. Max ~5 km². Please zoom in.")

    mode = "3D" if export_3d else "2D"
    print(f"\n=== VectoMap v6 | {mode} | 1:{scale} ===")

    # 1. Fetch
    buildings = roads = None
    if include_buildings:
        try:
            buildings = ox.features_from_bbox(
                bbox=(min_lon, min_lat, max_lon, max_lat), tags={"building": True})
            print(f"  buildings: {len(buildings)}")
        except Exception as e:
            print(f"  buildings failed: {e}")
    if include_roads:
        try:
            graph = ox.graph_from_bbox(
                bbox=(min_lon, min_lat, max_lon, max_lat), network_type="all")
            _, roads = ox.graph_to_gdfs(graph)
            print(f"  roads: {len(roads)}")
        except Exception as e:
            print(f"  roads failed: {e}")
    if buildings is None and roads is None:
        raise RuntimeError("No OSM data returned for this bbox.")

    # 2. Project
    ref = buildings if buildings is not None else roads
    utm_crs = ref.estimate_utm_crs()
    if buildings is not None: buildings = buildings.to_crs(utm_crs)
    if roads     is not None: roads     = roads.to_crs(utm_crs)

    # 3. Zero anchor
    all_geoms = []
    if buildings is not None: all_geoms += buildings.geometry.dropna().tolist()
    if roads     is not None: all_geoms += roads.geometry.dropna().tolist()
    bounds = unary_union(all_geoms).bounds
    min_x, min_y = bounds[0], bounds[1]

    # 4. Build DXF
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    doc.layers.add("BUILDINGS",      dxfattribs={"color": 7,   "lineweight": 25})
    doc.layers.add("BUILDINGS_FILL", dxfattribs={"color": 254, "lineweight": 0})
    doc.layers.add("BUILDINGS_3D",   dxfattribs={"color": 7,   "lineweight": 13})
    doc.layers.add("ROAD_MAJOR",     dxfattribs={"color": 5,   "lineweight": 50})
    doc.layers.add("ROAD_MINOR",     dxfattribs={"color": 4,   "lineweight": 25})
    doc.layers.add("ROAD_FOOT",      dxfattribs={"color": 3,   "lineweight": 13})

    if export_3d:
        set_shaded_viewport(doc)

    b_count = b_skip = 0

    # Buildings
    if include_buildings and buildings is not None:
        for _, row in buildings.iterrows():
            for poly in get_polygons(row.geometry):
                if poly is None or not poly.is_valid or poly.is_empty:
                    b_skip += 1; continue
                coords = list(poly.exterior.coords)
                if coords[0] == coords[-1]: coords = coords[:-1]
                if len(coords) < 3: b_skip += 1; continue
                coords_2d = transform_xy(coords, min_x, min_y, scale)
                try:
                    if not export_3d:
                        # 2D: filled outline
                        draw_2d_building(msp, coords_2d,
                                         layer="BUILDINGS",
                                         hatch_layer="BUILDINGS_FILL")
                    else:
                        # 3D: draw 2D outline ALWAYS (for base plan visibility)
                        msp.add_lwpolyline(coords_2d, close=True,
                                           dxfattribs={"layer": "BUILDINGS"})
                        # then draw the solid 3D extrusion
                        h = get_building_height(row, scale)
                        draw_3d_building(msp, coords_2d, h, layer="BUILDINGS_3D")
                    b_count += 1
                except Exception:
                    b_skip += 1

        print(f"  drew {b_count} buildings, skipped {b_skip}")

    # Roads
    # elevation=0.001 in 3D mode lifts roads just above the ground plane
    # so they are not buried under building floor geometry
    road_elevation = 0.001 if export_3d else 0
    r_count = 0
    if include_roads and roads is not None:
        for _, row in roads.iterrows():
            geom = row.geometry
            if geom is None or geom.geom_type != "LineString": continue
            try:
                layer  = get_road_layer(row.get("highway", ""))
                coords = transform_xy(list(geom.coords), min_x, min_y, scale)
                msp.add_lwpolyline(coords, dxfattribs={
                    "layer": layer, "elevation": road_elevation})
                r_count += 1
            except Exception:
                pass
        print(f"  drew {r_count} roads")

    # 5. Write — DXF is text, use StringIO then encode
    buf = io.StringIO()
    doc.write(buf)
    data = buf.getvalue().encode("utf-8")
    print(f"  output: {len(data):,} bytes")
    return data


if __name__ == "__main__":
    data = export_to_dxf_bytes(
        min_lon=77.2100, min_lat=28.6280,
        max_lon=77.2200, max_lat=28.6350,
        scale=1000, include_buildings=True,
        include_roads=True, export_3d=True,
    )
    with open("test_v6_3d.dxf", "wb") as f:
        f.write(data)
    print("Saved test_v6_3d.dxf")