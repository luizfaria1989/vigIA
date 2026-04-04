import geopandas as gpd

focos_goias = gpd.read_file("GO/GO.shp")
focos_goias.to_file("focos_goias_mapeado.geojson", driver="GeoJSON")