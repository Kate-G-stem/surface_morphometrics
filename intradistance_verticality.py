#! /usr/bin/env python
"""Measure intra-surface distances and optionally verticality for a pycurv-generated triangle graph file.

Usage: python intradistance_verticality.py file.gt [options]
"""

__author__ = "Benjamin Barad"
__email__ = "benjamin.barad@gmail.com"
__license__ = "GPLv3"

import click
import vtk
import numpy as np
import pandas
from pycurv import  TriangleGraph, io
from graph_tool import load_graph



def export_csv(tg, csvname):
    """Export all properties in a triangle graph to a CSV with indices for quick visualization with other programs"""
    print(f"Exporting graph data to CSV {csvname}")
    df = pandas.DataFrame()
    vector_properties = []
    scalar_properties = []
    properties = tg.graph.vertex_properties.keys()
    
    ## defined scalar types from the graph-tool documentation
    scalars = ["bool", "int16_t", "int32_t", "int64_t", "unsigned long","double", "long double"]
    
    ## iterative over properties and classify them as scalars or vectors
    for property in properties:
        type = tg.graph.vertex_properties[property].value_type()
        if type in scalars:
            scalar_properties.append(property)
        elif type[:6] == "vector":
            vector_properties.append(property)
    print("Scalar Properties to save: ", scalar_properties)
    print("Vector Properties to save: ", vector_properties)
    for property in scalar_properties:
        df[property] = tg.get_vertex_property_array(property)
    for vector_property in vector_properties:
        x,y,z = tg.graph.vp[vector_property].get_2d_array([0,1,2])
        df[vector_property+"_x"] = x
        df[vector_property+"_y"] = y
        df[vector_property+"_z"] = z
    df.to_csv(csvname, index_label="index")     

def get_dist_two_directions(point, normal, locator, dist_min=3, dist_max=400, tolerance=0.1):
    """Returns the distance and cell ID from a certain point along both the 
    positive and normal axis

    point: array of the point
    normal: array of the normal - recommended to use voted normals.
    locator: vtk cell locator object
    dist_min: minimum distance to consider (to avoid self-intersection)
    dist_max: maximum distance to consider
    tolerance: tolerance for the distance calculation
    """
    distances = []
    cell_ids = []
    for direction in [-normal, normal]:
        
        p0 = point + direction*dist_min
        pmax = point + direction*dist_max
        p1 = [0.,0.,0.]
        pcoords = [0,0,0]
        sub_id = vtk.mutable(-1)
        cell1_id = vtk.mutable(-1)
        t = vtk.mutable(0.) # parametric coordinate of the intersection - 0 to 1 if intersection is found
        locator.IntersectWithLine(p0, pmax, tolerance, t, p1, pcoords, sub_id,
                              cell1_id)
        distance = np.linalg.norm(p1-point)
        if cell1_id == -1:
            distances.append(np.nan)
            cell_ids.append(-1)
        elif distance > dist_max+1 or distance < dist_min-1: # Tolerance adjustment
            distances.append(np.nan)
            cell_ids.append(-1)       
        else:
            distances.append(np.linalg.norm(p1-point)) # distance in the direction of the normal
            cell_ids.append(int(cell1_id))
    # switch orders if the first distance is larger:
    if np.isnan(distances[0]):
        distances = distances[::-1]
        cell_ids = cell_ids[::-1]
    elif np.isnan(distances[1]):
        # Only one distance
        pass
    elif distances[0] > distances[1]:
        # print("Distances misordered, flipping")
        distances = distances[::-1]
        cell_ids = cell_ids[::-1]
    
    # close dist, close id, far dist, far id
    assert np.isnan(distances[1]) or distances[0]<=distances[1]
    
    return distances[0], cell_ids[0], distances[1], cell_ids[1]


def surface_verticality(graph_file, exportcsv=False):
    """Measure the verticality of the surface of a graph file.
    
    graph_file (str): path to a graph file generated by pycurv
    """
    tg = TriangleGraph()
    tg.graph = load_graph(graph_file)
    z_values = tg.graph.vp.n_v.get_2d_array([2])[0]
    # Normals are unit scaled by pycurv, so the angle between is the arccos with (0,0,1) - or just the z value!
    # Report in degrees - CryoEM tends to use degrees.
    vert = 90-np.abs(np.arccos(z_values)*180/np.pi-90) 
    verticality = tg.graph.new_vertex_property("float")
    verticality.a = vert
    tg.graph.vp["verticality"] = verticality
    tg.graph.save(graph_file)
    if exportcsv:
        export_csv(tg, graph_file[:-4]+".csv")

def surface_self_distances(graph_file, surface_file, dist_min=6, dist_max=400, tolerance=0.1, exportcsv=True):
    """Returns the distances between all vertices of two surfaces - 
    inspired by find_1_distance in pycurv

    graph_file: graph-tool graph filename of the surface
    surface_file: vtk surface filename of the first surface
    dist_min: minimum distance to consider (to avoid self-intersection)
    dist_max: maximum distance to consider (stick to physiological relevant distances)
    tolerance: tolerance for the distance calculation (recommended to be 0.1)
    """
    # Initialize stuff
    print("Loading graph and surface")
    surface = io.load_poly(surface_file)
    locator = vtk.vtkStaticCellLocator()
    locator.SetDataSet(surface)
    locator.BuildLocator()
    tg = TriangleGraph()
    tg.graph = load_graph(graph_file)
    xyz = tg.graph.vp.xyz.get_2d_array([0,1,2]).transpose()
    normal = tg.graph.vp.n_v.get_2d_array([0,1,2]).transpose() # use n_v for voted normals
    # Initialize variables
    print("Initializing variables")
    close_distances = tg.graph.new_vertex_property("float")
    close_id = tg.graph.new_vertex_property("long")
    far_distances = tg.graph.new_vertex_property("float")
    far_id = tg.graph.new_vertex_property("long")
    # Vectorized distance processor
    # Calculate distances
    print("Calculating distances")
    for i in range(len(close_distances.a)):
        close_distances.a[i], close_id.a[i], far_distances.a[i], far_id.a[i] = get_dist_two_directions(xyz[i], normal[i], locator, dist_min, dist_max, tolerance=0.001)
    # Write out distances
    print(np.nanmin(close_distances.a), np.nanmax(close_distances.a))
    print(np.nanmin(far_distances.a), np.nanmax(far_distances.a))
    print("Writing out distances")
    tg.graph.vp.self_dist_min = close_distances
    tg.graph.vp.self_id_min = close_id
    tg.graph.vp.self_dist_far = far_distances
    tg.graph.vp.self_id_far = far_id
    # Save graph
    tg.graph.save(graph_file)
    surf = tg.graph_to_triangle_poly()
    io.save_vtp(surf, surface_file)
    # Save CSV with all features
    if exportcsv:
        csvname = graph_file[:-3]+".csv"
        print("Writing out CSV: "+csvname)
        export_csv(tg, csvname)

    return tg


@click.command()
@click.argument('graph_file', type=click.Path(exists=True))
@click.option('--verticality', type=bool, default=True, help="Calculate orientation relative to growth plane (xy plane)? Default True.")
@click.option('--dist_min', type=int, default=3, help="Minimum distance to consider (to avoid self-intersection)")
@click.option('--dist_max', type=int, default=400, help="Maximum distance to consider (stick to physiological relevant distances)")
@click.option('--tolerance', type=float, default=0.1, help="Tolerance for the distance calculation (recommended to be 0.1)")
@click.option('--exportcsv', type=bool, default=True, help="Export CSV with all features?")
def intra_cli(graph_file, verticality, dist_min, dist_max, tolerance, exportcsv):
    """Run intra-surface distance and optionally verticality measurements for a surface"""
    surface_file = graph_file[:-3]+".vtp"
    if verticality:
        surface_verticality(graph_file)
    surface_self_distances(graph_file, surface_file, dist_min=dist_min, dist_max=dist_max, tolerance=tolerance, exportcsv=exportcsv)



if __name__ == "__main__":
    intra_cli()

 