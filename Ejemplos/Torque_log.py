import base64
import io
import pandas as pd
import numpy as np
import plotly.express as px
from dash import Dash, html, dcc, Input, Output, dash_table

app = Dash(__name__)
app.title = "Torque Log Visualizer"

app.layout = html.Div([
    html.Div([
        html.H2("Torque Log Visualizer", style={'marginBottom': '20px'}),

        dcc.Upload(
            id='upload-data',
            children=html.Div(['\ud83d\udcc1 Drag and Drop o ', html.A('Seleccionar CSV')]),
            style={
                'width': '100%', 'height': '60px', 'lineHeight': '60px',
                'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px',
                'textAlign': 'center', 'margin': '10px 0'
            },
            multiple=False
        ),

        html.Label("Seleccionar m\u00e9trica a graficar"),
        dcc.RadioItems(
            id='metric-dropdown',
            labelStyle={'display': 'block', 'margin': '3px 0'}
        ),

        html.Label("Columnas para hover en mapa", style={'marginTop': '20px'}),
        dcc.Checklist(
            id='hover-columns-dropdown',
            labelStyle={'display': 'block', 'margin': '3px 0'}
        ),

        html.Label("Modo oscuro", style={'marginTop': '20px'}),
        dcc.Checklist(
            id='dark-mode-toggle',
            options=[{'label': 'Activar', 'value': 'dark'}],
            value=[],
            labelStyle={'display': 'inline-block', 'marginRight': '10px'}
        ),
    ], style={
        'width': '300px',
        'padding': '20px',
        'borderRight': '1px solid #ccc',
        'flexShrink': 0
    }),

    html.Div(id='output-visuals', style={'flexGrow': 1, 'padding': '20px'})
], style={'display': 'flex', 'minHeight': '100vh'})

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
     Output('output-visuals', 'children'),
     Output('output-visuals', 'style')],
    [Input('upload-data', 'contents'),
     Input('metric-dropdown', 'value'),
     Input('hover-columns-dropdown', 'value'),
     Input('dark-mode-toggle', 'value')]
)
def update_output(contents, selected_metric, hover_columns, dark_mode):
    if not contents:
        return [], [], None, [], html.Div("\ud83d\udd3c Sub\u00ed un archivo CSV para comenzar."), {'flexGrow': 1, 'padding': '20px'}

    df = parse_contents(contents)

    excluir_columnas = [
        'Latitude', 'Longitude',
        'Horizontal Dilution of Precision', 'Bearing',
        'G(x)', 'G(y)', 'G(z)', 'G(calibrated)'
    ]

    metric_options = [
        {'label': col, 'value': col}
        for col in df.columns
        if df[col].dtype in ['float64', 'int64'] and col not in excluir_columnas
    ]

    hover_options = [
        {'label': col, 'value': col}
        for col in df.columns
        if col not in excluir_columnas
    ]

    if selected_metric is None and metric_options:
        selected_metric = metric_options[0]['value']
    if hover_columns is None:
        hover_columns = ['Time', selected_metric]

    # Estilo de fondo
    is_dark = 'dark' in (dark_mode or [])
    dark_style = {
        'flexGrow': 1,
        'padding': '20px',
        'backgroundColor': '#1e1e1e' if is_dark else 'white',
        'color': 'white' if is_dark else 'black'
    }

    if 'Latitude' in df.columns and 'Longitude' in df.columns and selected_metric:
        color_scale = px.colors.sequential.RdBu if any(df[selected_metric] < 0) and any(df[selected_metric] > 0) else px.colors.sequential.Jet
        midpoint = 0 if color_scale == px.colors.sequential.RdBu else None

        fig_map = px.scatter_map(
            df,
            lat='Latitude',
            lon='Longitude',
            color=selected_metric,
            zoom=12,
            height=500,
            color_continuous_scale=color_scale,
            color_continuous_midpoint=midpoint,
            hover_data=[col for col in hover_columns if col in df.columns and col not in excluir_columnas]
        )

        map_style = "carto-darkmatter" if is_dark else "carto-positron"
        fig_map.update_layout(
            mapbox={"style": map_style},
            margin={"r": 0, "t": 0, "l": 0, "b": 0}
        )

        map_graph = dcc.Graph(
            figure=fig_map,
            config={
                'displayModeBar': 'hover',
                'displaylogo': False,
                'modeBarButtonsToAdd': ['zoom2d', 'pan2d', 'resetViewMapbox'],
                'modeBarStyle': {'top': '40px', 'right': '20px'}
            }
        )
    else:
        map_graph = html.Div("\u26a0\ufe0f El archivo no contiene columnas 'Latitude' y 'Longitude'.")

    if 'Time' in df.columns and selected_metric:
        fig_time = px.line(df.dropna(subset=[selected_metric]), x='Time', y=selected_metric, title=f"{selected_metric} en el tiempo")
        time_graph = html.Div([
            html.H4("\ud83d\udcc8 M\u00e9trica temporal"),
            dcc.Graph(figure=fig_time)
        ], style={'marginTop': '60px'})
    else:
        time_graph = html.Div("\u26a0\ufe0f No se puede graficar el tiempo.")

    if selected_metric:
        col_data = df[selected_metric].dropna()
        unidades = {
            'GPS Speed (Kilometers/hour)': 'km/h',
            'Engine RPM(rpm)': 'rpm',
            'Ambient air temp(\u00b0C)': '\u00b0C',
            'Engine Coolant Temperature(\u00b0C)': '\u00b0C',
            'Fuel flow rate/hour(l/hr)': 'l/hr',
            'Mass Air Flow Rate(g/s)': 'g/s',
            'Throttle Position(Manifold)(%)': '%',
            'Timing Advance(\u00b0)': '\u00b0',
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
            columns=[
                {"name": "Statistic", "id": "Statistic"},
                {"name": "Value", "id": "Value", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "Unit", "id": "Unit"}
            ],
            style_table={
                'maxHeight': '300px',
                'overflowY': 'auto',
                'width': '400px'
            },
            style_cell={
                'padding': '6px',
                'fontSize': '14px',
                'whiteSpace': 'normal',
            },
            style_cell_conditional=[
                {'if': {'column_id': 'Statistic'}, 'textAlign': 'left', 'minWidth': '180px', 'width': '180px', 'maxWidth': '180px'},
                {'if': {'column_id': 'Value'}, 'textAlign': 'right', 'minWidth': '100px', 'width': '100px', 'maxWidth': '100px'},
                {'if': {'column_id': 'Unit'}, 'textAlign': 'left', 'minWidth': '60px', 'width': '60px', 'maxWidth': '60px'}
            ],
            style_header={
                'fontWeight': 'bold',
                'backgroundColor': 'white' if not is_dark else '#333',
                'color': 'black' if not is_dark else 'white'
            }
        )
    else:
        stats_table = html.Div("\u26a0\ufe0f No se pudo calcular estad\u00edsticas.")

    return metric_options, hover_options, selected_metric, hover_columns, html.Div([
        html.H4("\ud83d\udccd Mapa del recorrido"),
        map_graph,
        time_graph,
        html.H4("\ud83d\udcca Estad\u00edsticas"),
        stats_table
    ]), dark_style

if __name__ == '__main__':
    app.run(debug=False)
