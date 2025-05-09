import base64
import io
import pandas as pd
import numpy as np
import plotly.express as px
from dash import Dash, html, dcc, Input, Output, dash_table, State, no_update, ctx, callback_context
import re

app = Dash(__name__)

# Agregar fuente Inter desde Google Fonts
font_link = html.Link(
    rel='stylesheet',
    href='https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap'
)
app.title = "Torque Log Visualizer"

app.layout = html.Div([
    font_link,
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

        html.Button("⬇️ Descargar Excel", id="download-button", style={'marginTop': '10px'}),
        dcc.Download(id="download-dataframe-xlsx"),

        html.Hr(),
        html.Label("Seleccionar uso de variables"),
        html.Div(id='variable-usage-checklist-container')
    ], style={
        'width': '350px',
        'padding': '20px',
        'borderRight': '1px solid #ccc',
        'flexShrink': 0
    }),

    html.Div(id='output-visuals', style={'flexGrow': 1, 'padding': '20px'})
], style={'fontFamily': 'Inter, sans-serif', 'display': 'flex', 'minHeight': '100vh'})


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

stored_df = {}

@app.callback(
    Output('variable-usage-checklist-container', 'children'),
    Input('upload-data', 'contents')
)
def render_variable_checklists(contents):
    if not contents:
        return html.Div("📤 Subí un archivo para comenzar.")

    df = parse_contents(contents)
    stored_df['data'] = df

    exclude = [
        'Latitude', 'Longitude', 'Horizontal Dilution of Precision', 'Bearing',
        'G(x)', 'G(y)', 'G(z)', 'G(calibrated)'
    ]
    variables = [col for col in df.columns if col not in exclude and pd.api.types.is_numeric_dtype(df[col])]

    return html.Div([
        html.Label("Seleccionar métrica (una sola):"),
        dcc.RadioItems(
            id='metric-radio',
            options=[{'label': var, 'value': var} for var in variables],
            labelStyle={'display': 'block', 'margin': '2px 0'}
        ),
        html.Br(),
        html.Label("Columnas para hover (pueden ser varias):"),
        dcc.Checklist(
            id='hover-checklist',
            options=[{'label': var, 'value': var} for var in variables],
            labelStyle={'display': 'block', 'margin': '2px 0'}
        ),
        html.Br(),
        html.Label("Seleccionar variables para graficar contra el tiempo:"),
        dcc.Checklist(
            id='multi-timeseries-vars',
            options=[{'label': var, 'value': var} for var in variables],
            labelStyle={'display': 'block', 'margin': '2px 0'}
        )
    ])

@app.callback(
    Output('output-visuals', 'children'),
    [Input('upload-data', 'contents'),
     Input('metric-radio', 'value'),
     Input('hover-checklist', 'value'),
     Input('multi-timeseries-vars', 'value')]
)
def update_visuals(contents, metrica, hover_columns, timeseries_vars):
    if not contents or not metrica:
        return html.Div("📤 Subí un archivo y seleccioná una métrica."),

    df = parse_contents(contents)
    stored_df['data'] = df

    if 'Latitude' in df.columns and 'Longitude' in df.columns:
        fig_map = px.scatter_map(
            df,
            lat='Latitude',
            lon='Longitude',
            color=metrica,
            zoom=12,
            height=500,
            color_continuous_scale='Jet',
            hover_data=[col for col in (hover_columns or []) if col in df.columns]
        )
        fig_map.update_layout(font=dict(size=12, family="Inter"), mapbox={"style": "carto-positron"}, margin={"r": 0, "t": 0, "l": 0, "b": 0})

        map_graph = dcc.Graph(figure=fig_map, config={
            'displayModeBar': 'hover',
            'displaylogo': False,
            'modeBarButtonsToAdd': ['zoom2d', 'pan2d', 'resetViewMapbox'],
            'modeBarStyle': {'top': '40px', 'right': '20px'}
        })
    else:
        map_graph = html.Div("⚠️ No hay coordenadas para mostrar el mapa.")

    # Single metric time plot
    fig_time = px.line(df.dropna(subset=[metrica]), x='Time', y=metrica, title=f"{metrica} en el tiempo")
    fig_time.update_layout(font=dict(size=12, family="Inter"))

    # Multi-variable time series plot
    multi_graph = None
    if timeseries_vars:
        df_melt = df[['Time'] + timeseries_vars].melt(id_vars='Time', var_name='Variable', value_name='Valor')
        fig_multi = px.line(df_melt.dropna(), x='Time', y='Valor', color='Variable', title="Variables seleccionadas en el tiempo")
        fig_multi.update_layout(font=dict(size=12, family="Inter"))
        multi_graph = dcc.Graph(figure=fig_multi, config={
            'toImageButtonOptions': {
                'format': 'png',
                'filename': 'comparativa_variables',
                'height': 600,
                'width': 1000,
                'scale': 2
            },
            'modeBarButtonsToAdd': ['toImage'],
            'displaylogo': False
        })

    col_data = df[metrica].dropna()
    match = re.search(r'\(([^()]*)\)\s*$', metrica)
    unidad = match.group(1) if match else ''
    if unidad == 'Kilometers/hour':
        unidad = 'km/h'

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
        style_table={'maxHeight': '300px', 'overflowY': 'auto', 'width': '400px'},
        style_cell={
            'padding': '6px',
            'fontSize': '12px',
            'whiteSpace': 'normal'
        },
        style_cell_conditional=[
            {'if': {'column_id': 'Statistic'}, 'textAlign': 'left', 'minWidth': '180px', 'width': '180px', 'maxWidth': '180px'},
            {'if': {'column_id': 'Value'}, 'textAlign': 'right', 'minWidth': '100px', 'width': '100px', 'maxWidth': '100px'},
            {'if': {'column_id': 'Unit'}, 'textAlign': 'left', 'minWidth': '60px', 'width': '60px', 'maxWidth': '60px'}
        ],
        style_header={
            'fontWeight': 'bold',
            'backgroundColor': 'white',
            'color': 'black'
        }
    )

    return html.Div([
        html.H4("📍 Mapa del recorrido"),
        map_graph,
        html.Div([
        html.H4("📈 Métrica temporal"),
        dcc.Graph(figure=fig_time)
    ], style={'marginTop': '80px'}),
        html.Div([
            html.H4("📉 Comparativa de variables seleccionadas"),
            multi_graph if multi_graph else html.Div("Seleccioná variables para comparar.")
        ], style={'marginTop': '80px'}),
        html.Div([
        html.H4("📊 Estadísticas"),
            stats_table
        ], style={'marginTop': '40px'})
    ], style={'padding': '20px'})

@app.callback(
    Output("download-dataframe-xlsx", "data"),
    Input("download-button", "n_clicks"),
    prevent_initial_call=True
)
def download_excel(n_clicks):
    if 'data' in stored_df:
        return dcc.send_data_frame(stored_df['data'].to_excel, "torque_log.xlsx", index=False)
    return no_update

if __name__ == '__main__':
    app.run(debug=False)
