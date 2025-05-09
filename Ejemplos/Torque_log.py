import base64
import io
import pandas as pd
import numpy as np
import plotly.express as px
from dash import Dash, html, dcc, Input, Output, dash_table, State, no_update

app = Dash(__name__)
app.title = "Torque Log Visualizer"

app.layout = html.Div([
    html.Div([
        html.H2("Torque Log Visualizer", style={'marginBottom': '20px'}),

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

        html.Label("Modo oscuro", style={'marginTop': '20px'}),
        dcc.Checklist(
            id='dark-mode-toggle',
            options=[{'label': 'Activar', 'value': 'dark'}],
            value=[],
            labelStyle={'display': 'inline-block', 'marginRight': '10px'}
        ),

        html.Hr(),
        html.Label("Seleccionar uso de variables"),
        dash_table.DataTable(
            id='variable-usage-table',
            columns=[
                {"name": "Variable", "id": "Variable", "presentation": "markdown"},
                {"name": "Uso", "id": "Uso", "presentation": "dropdown"}
            ],
            editable=True,
            row_deletable=False,
            style_table={
                'overflowY': 'auto',
                'maxHeight': '250px',
                'minWidth': '100%'
            },
            style_cell={
                'textAlign': 'left',
                'padding': '3px',
                'fontSize': '13px',
                'minWidth': '60px',
                'maxWidth': '180px',
                'overflow': 'hidden',
                'textOverflow': 'ellipsis',
                'whiteSpace': 'nowrap'
            },
            style_cell_conditional=[
                {
                    'if': {'column_id': 'Uso'},
                    'width': '100px',
                    'minWidth': '80px',
                    'maxWidth': '120px',
                    'textAlign': 'center'
                }
            ],
            style_header={'fontWeight': 'bold'},
            dropdown={
                'Uso': {
                    'options': [
                        {'label': 'Métrica', 'value': 'metrica'},
                        {'label': 'Hover', 'value': 'hover'},
                        {'label': 'Ignorar', 'value': 'ignorar'}
                    ]
                }
            }
        )
    ], style={
        'width': '350px',
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
        df.drop(columns=["GPS Speed (Meters/second)"] , inplace=True)

    return df

@app.callback(
    [Output('variable-usage-table', 'data'),
     Output('variable-usage-table', 'dropdown')],
    Input('upload-data', 'contents')
)
def populate_variable_table(contents):
    if not contents:
        return [], no_update

    df = parse_contents(contents)
    exclude = [
        'Latitude', 'Longitude', 'Horizontal Dilution of Precision', 'Bearing',
        'G(x)', 'G(y)', 'G(z)', 'G(calibrated)'
    ]
    variables = [col for col in df.columns if col not in exclude and df[col].dtype in ['float64', 'int64']]
    data = [{'Variable': var, 'Uso': 'ignorar'} for var in variables]
    return data, no_update

@app.callback(
    Output('output-visuals', 'children'),
    [Input('upload-data', 'contents'),
     Input('variable-usage-table', 'data'),
     Input('dark-mode-toggle', 'value')]
)
def update_visuals(contents, usage_data, dark_mode):
    if not contents or not usage_data:
        return html.Div("📤 Subí un archivo y seleccioná al menos una variable."),

    df = parse_contents(contents)

    metrica = next((item['Variable'] for item in usage_data if item['Uso'] == 'metrica'), None)
    hover_columns = [item['Variable'] for item in usage_data if item['Uso'] == 'hover']

    is_dark = 'dark' in (dark_mode or [])
    dark_style = {
        'backgroundColor': '#1e1e1e' if is_dark else 'white',
        'color': 'white' if is_dark else 'black',
        'padding': '20px'
    }

    if not metrica:
        return html.Div("⚠️ No seleccionaste ninguna variable como métrica."),

    if 'Latitude' in df.columns and 'Longitude' in df.columns:
        fig_map = px.scatter_map(
            df,
            lat='Latitude',
            lon='Longitude',
            color=metrica,
            zoom=12,
            height=500,
            color_continuous_scale='Jet',
            hover_data=[col for col in hover_columns if col in df.columns]
        )
        map_style = "carto-darkmatter" if is_dark else "carto-positron"
        fig_map.update_layout(mapbox={"style": map_style}, margin={"r": 0, "t": 0, "l": 0, "b": 0})

        map_graph = dcc.Graph(figure=fig_map, config={
            'displayModeBar': 'hover',
            'displaylogo': False,
            'modeBarButtonsToAdd': ['zoom2d', 'pan2d', 'resetViewMapbox'],
            'modeBarStyle': {'top': '40px', 'right': '20px'}
        })
    else:
        map_graph = html.Div("⚠️ No hay coordenadas para mostrar el mapa.")

    fig_time = px.line(df.dropna(subset=[metrica]), x='Time', y=metrica, title=f"{metrica} en el tiempo")

    col_data = df[metrica].dropna()
    stats_data = pd.DataFrame({
        'Statistic': ['Mean', 'Max', 'Min', 'Start', 'End', '25%', '50%', '75%', '90%'],
        'Value': [
            col_data.mean(), col_data.max(), col_data.min(),
            col_data.iloc[0], col_data.iloc[-1],
            np.percentile(col_data, 25),
            np.percentile(col_data, 50),
            np.percentile(col_data, 75),
            np.percentile(col_data, 90)
        ]
    })

    stats_table = dash_table.DataTable(
        data=stats_data.to_dict('records'),
        columns=[
            {"name": "Statistic", "id": "Statistic"},
            {"name": "Value", "id": "Value", "type": "numeric", "format": {"specifier": ".2f"}}
        ],
        style_table={'maxHeight': '300px', 'overflowY': 'auto', 'width': '400px'},
        style_cell={
            'padding': '6px',
            'fontSize': '14px',
            'whiteSpace': 'normal',
            'textAlign': 'left'
        },
        style_header={
            'fontWeight': 'bold',
            'backgroundColor': '#333' if is_dark else 'white',
            'color': 'white' if is_dark else 'black'
        }
    )

    return html.Div([
        html.H4("📍 Mapa del recorrido"),
        map_graph,
        html.Div([
            html.H4("📈 Métrica temporal"),
            dcc.Graph(figure=fig_time)
        ], style={'marginTop': '40px'}),
        html.Div([
            html.H4("📊 Estadísticas"),
            stats_table
        ], style={'marginTop': '40px'})
    ], style=dark_style)

if __name__ == '__main__':
    app.run(debug=False)
