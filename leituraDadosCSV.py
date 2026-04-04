import geopandas as gpd

focos_goias = gpd.read_file("GO/GO.shp")

focos_goias_ml = focos_goias.copy()
focos_goias_ml['geometria_texto'] = focos_goias_ml.geometry.apply(lambda x: x.wkt)
focos_goias_ml = focos_goias_ml.drop(columns=['geometry'])

focos_goias_ml.to_csv("base_focos_ml.csv", index=False, encoding='utf-8')