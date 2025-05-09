import base64
import io
import pandas as pd
import numpy as np
import plotly.express as px
from dash import Dash, html, dcc, Input, Output, dash_table, ctx

app = Dash(__name__)
app.title = "Torque Log Visualizer"

app.layout = html.Div([
    html.H2("Torque Log Visualizer"),

    dcc.Upload(
        id='upload-data',
        children=html.Div(['📁 Drag and Drop o ', html.A('Seleccionar CSV')]),
        style={
            'width': '100%', 'height': '60px', 'lineHeight': '60px',
            'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px',
            'textAlign': 'center', 'margin': '10px 0'
        },
        multiple=False
    ),

    dcc.Dropdown(id='metric-dropdown', placeholder='Seleccionar métrica para graficar'),
    dcc.Dropdown(id='hover-columns-dropdown', multi=True, placeholder='Columnas para hover en mapa'),

    html.Div(id='output-visuals')
])

def parse_contents(contents):
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    csv_string = decoded.decode('utf-8')
    df = pd.read_csv(io.StringIO(csv_string), skipinitialspace=True, na_values=["-"])

    if "Device Time" in df.columns:
        try:
            df["Time"] = pd.to_datetime(df["Device Time"], format='%d-%b-%Y %H:%M:%S.%f')
        except:
            df["Time"] = pd.to_datetime(df["Device Time"], errors='coerce')

    if "GPS Speed (Meters/second)" in df.columns:
        df["GPS Speed (Kilometers/hour)"] = df["GPS Speed (Meters/second)"] * 3.6
        df.drop(columns=["GPS Speed (Meters/second)"], inplace=True)

    return df

@app.callback(
    [Output('metric-dropdown', 'options'),
     Output('hover-columns-dropdown', 'options'),
     Output('metric-dropdown', 'value'),
     Output('hover-columns-dropdown', 'value'),
     Output('output-visuals', 'children')],
    [Input('upload-data', 'contents'),
     Input('metric-dropdown', 'value'),
     Input('hover-columns-dropdown', 'value')]
)
def update_output(contents, selected_metric, hover_columns):
    if not contents:
        return [], [], None, [], html.Div("🔼 Subí un archivo CSV para comenzar.")

    df = parse_contents(contents)

    metric_options = [{'label': col, 'value': col} for col in df.columns if df[col].dtype in ['float64', 'int64']]

    # Excluir lat/lon del hover
    hover_exclude = ['Latitude', 'Longitude']
    hover_options = [{'label': col, 'value': col} for col in df.columns if col not in hover_exclude]

    if selected_metric is None and metric_options:
        selected_metric = metric_options[0]['value']
    if hover_columns is None:
        hover_columns = ['Time', selected_metric]

    # --- MAPA DEL RECORRIDO ---
    if 'Latitude' in df.columns and 'Longitude' in df.columns and selected_metric:
        if any(df[selected_metric] < 0) and any(df[selected_metric] > 0):
            color_scale = px.colors.sequential.RdBu
            midpoint = 0
        else:
            color_scale = px.colors.sequential.Jet
            midpoint = None

        fig_map = px.scatter_map(
            df,
            lat='Latitude',
            lon='Longitude',
            color=selected_metric,
            zoom=12,
            height=500,
            color_continuous_scale=color_scale,
            color_continuous_midpoint=midpoint,
            hover_data=[col for col in hover_columns if col in df.columns and col not in hover_exclude]
        )

        fig_map.update_layout(
            mapbox={"style": "carto-positron"},
            margin={"r": 0, "t": 0, "l": 0, "b": 0}
        )

        map_graph = dcc.Graph(
            figure=fig_map,
            config={
                'displayModeBar': 'hover',
                'displaylogo': False,
                'modeBarButtonsToAdd': ['zoom2d', 'pan2d', 'resetViewMapbox'],
                'modeBarStyle': {
                    'top': '40px',
                    'right': '20px'
                }
            }
        )
    else:
        map_graph = html.Div("⚠️ El archivo no contiene columnas 'Latitude' y 'Longitude'.")

    # --- GRAFICO TEMPORAL ---
    if 'Time' in df.columns and selected_metric:
        fig_time = px.line(df.dropna(subset=[selected_metric]), x='Time', y=selected_metric, title=f"{selected_metric} en el tiempo")
        time_graph = html.Div([
            html.H4("📈 Métrica temporal"),
            dcc.Graph(figure=fig_time)
        ], style={'marginTop': '60px'})
    else:
        time_graph = html.Div("⚠️ No se puede graficar el tiempo.")

    # --- ESTADISTICAS ---
    if selected_metric:
        col_data = df[selected_metric].dropna()

        # Agregar unidades por métrica
        unidades = {
            'GPS Speed (Kilometers/hour)': 'km/h',
            'Engine RPM(rpm)': 'rpm',
            'Ambient air temp(°C)': '°C',
            'Engine Coolant Temperature(°C)': '°C',
            'Fuel flow rate/hour(l/hr)': 'l/hr',
            'Mass Air Flow Rate(g/s)': 'g/s',
            'Throttle Position(Manifold)(%)': '%',
            'Timing Advance(°)': '°',
            'Voltage (Control Module)(V)': 'V'
        }
        unidad = unidades.get(selected_metric, '')

        stats_data = pd.DataFrame({
            'Statistic': ['Mean', 'Max', 'Min', 'Start', 'End', '25%', '50%', '75%', '90%'],
            'Value': [
                col_data.mean(), col_data.max(), col_data.min(),
                col_data.iloc[0], col_data.iloc[-1],
                np.percentile(col_data, 25),
                np.percentile(col_data, 50),
                np.percentile(col_data, 75),
                np.percentile(col_data, 90)
            ],
            'Unit': [unidad] * 9
        })

        stats_table = dash_table.DataTable(
            data=stats_data.to_dict('records'),
            columns=[{"name": i, "id": i} for i in stats_data.columns],
            style_table={'maxHeight': '300px', 'overflowY': 'auto'},
            style_cell={'textAlign': 'left'},
            style_header={'fontWeight': 'bold'}
        )
    else:
        stats_table = html.Div("⚠️ No se pudo calcular estadísticas.")

    return metric_options, hover_options, selected_metric, hover_columns, html.Div([
        html.H4("📍 Mapa del recorrido"),
        map_graph,
        time_graph,
        html.H4("📊 Estadísticas"),
        stats_table
    ])

if __name__ == '__main__':
    app.run(debug=False)
