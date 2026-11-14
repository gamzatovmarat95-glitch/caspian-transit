"""Overview sea corridors, checked against the bundled coarse coastline; not ship tracks."""
import copy

VERSION = 'caspian-overview-sea-2'
COLORS = {'olya-anzali': '#2d74ac', 'makh-amirabad': '#8061a8', 'olya-amirabad': '#bc7b42'}
WAYPOINTS = {
    'olya-anzali': [[45.55, 47.8], [44.8, 48.3], [43.3, 48.9], [41.7, 50.2], [40.3, 51.0], [38.5, 50.5], [37.65, 49.9], [37.55, 49.5]],
    'makh-amirabad': [[42.98, 47.56], [42.65, 48.0], [41.7, 49.6], [40.3, 51.1], [38.5, 52.5], [37.25, 53.3], [36.98, 53.37]],
    'olya-amirabad': [[45.55, 47.8], [44.8, 48.5], [43.3, 49.5], [41.7, 51.0], [39.5, 52.5], [37.4, 53.3], [36.98, 53.37]],
}


def sea_corridor(route):
    if route.get('seaGeometry'):
        return copy.deepcopy(route['seaGeometry'])
    points = copy.deepcopy(WAYPOINTS.get(route['id']))
    if points is None:
        return None
    # Corner cutting keeps the overview legible without inventing road/rail paths.
    for _ in range(3):
        refined = [points[0]]
        for a, b in zip(points, points[1:]):
            refined.extend([[.75*a[j]+.25*b[j] for j in (0, 1)],
                            [.25*a[j]+.75*b[j] for j in (0, 1)]])
        points = refined + [points[-1]]
    return points


def land_connections(routes, ports):
    """Shared overview legs from the configured multimodal route waypoints."""
    port_by_id = {port['id']: port for port in ports}
    connections = {}
    for route in routes:
        points = route['geometry']
        origin = port_by_id[route['from']]
        destination = port_by_id[route['to']]
        start = min(
            range(len(points)),
            key=lambda i: (points[i][0] - origin['lat']) ** 2
                + (points[i][1] - origin['lon']) ** 2,
        )
        end = min(
            range(start + 1, len(points)),
            key=lambda i: (points[i][0] - destination['lat']) ** 2
                + (points[i][1] - destination['lon']) ** 2,
        )
        legs = [
            (
                f"origin-{route['inlandMode']}-{origin['id']}",
                route['inlandMode'],
                f"Волгоград → {origin['name']}",
                points[:start + 1],
            ),
            (
                f"destination-road-{destination['id']}",
                'road',
                f"{destination['name']} → Тегеран",
                points[end:],
            ),
        ]
        for identifier, mode, name, geometry in legs:
            if len(geometry) < 2:
                continue
            if identifier not in connections:
                connections[identifier] = dict(
                    id=identifier,
                    mode=mode,
                    name=name,
                    geometry=copy.deepcopy(geometry),
                    routeIds=[],
                )
            connections[identifier]['routeIds'].append(route['id'])
    return list(connections.values())
