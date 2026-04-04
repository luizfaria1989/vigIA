import geopandas as gpd
import folium

focos_goias = gpd.read_file("GO/GO.shp")

focos_goias['NOME_MUNIC'] = focos_goias['NOME_MUNIC'].str.replace(r'[{}"\']', '', regex=True)

centro_goias = [-15.8270, -49.8362]
mapa = folium.Map(location=centro_goias, zoom_start=6)

folium.GeoJson(
    focos_goias,
    style_function=lambda x: {
        'fillColor': '#ff4500',
        'color': '#8b0000',
        'weight': 1,
        'fillOpacity': 0.6
    },
    tooltip=folium.GeoJsonTooltip(
        fields=['NOME_MUNIC', 'DT_PASSAGE', 'AREA_TOTAL', 'Q_FOCOS', 'FRP_MED', 'VE_EXPANSA'],
        aliases=['Município:', 'Data/Hora:', 'Área Total:', 'Qtd Focos:', 'Potência Média (FRP):', 'Veloc. Expansão:'],
        localize=True
    )
).add_to(mapa)

mapa.save("visualizacao_focos_completa.html")