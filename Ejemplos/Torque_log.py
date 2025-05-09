import base64
import io
import pandas as pd
import plotly.express as px
from dash import Dash, html, dcc, Input, Output, State, callback_context, dash_table
import dash_loading_spinners as dls
import numpy as np

FA = "https://use.fontawesome.com/releases/v5.8.1/css/all.css"

def remove_duplicate_header(csv_content, header_row=0):
    lines = csv_content.split("\n")
    header = lines[header_row]
    unique_lines = [header] + [line for i, line in enumerate(lines) if line != header and i != header_row]
    return "\n".join(unique_lines)

def parse_contents(contents):
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    try:
        # Intentar leer como CSV sin validar content_type
        csv_string = decoded.decode('utf-8')
        csv_string_no_dup_header = remove_duplicate_header(csv_string)
        df = pd.read_csv(io.StringIO(csv_string_no_dup_header), skipinitialspace=True, na_values=["-"])
        
        if "Device Time" in df.columns:
            try:
                df["Time"] = pd.to_datetime(df["Device Time"], format='%d-%b-%Y %H:%M:%S.%f')
            except ValueError:
                try:
                    df["Time"] = pd.to_datetime(df["Device Time"])
                except ValueError as e2:
                    print(f"Error converting 'Device Time': {e2}")
                    return None, "Error parsing 'Device Time'. Check the format."
        elif "GPS Time" in df.columns:
            try:
                df["Time"] = pd.to_datetime(df["GPS Time"])
            except ValueError as e:
                print(f"Error converting 'GPS Time': {e}")
                return None, "Error parsing 'GPS Time'. Check the format."
                
    except Exception as e:
        print(e)
        return None, 'There was an error processing the file.'
    
     # Conversión de velocidad a km/h
    if "GPS Speed (Meters/second)" in df.columns:
        df["GPS Speed (km/h)"] = df["GPS Speed (Meters/second)"] * 3.6
    
    return df, ''


app = Dash(__name__, external_stylesheets=[FA], title="Torque Logs Visualizer")

app.layout = html.Div([
    dcc.Upload(
        id='upload-data',
        children=html.Div(['Drag and Drop or ', html.A('Select a .csv File')]),
        style={
            'width': '100%', 'height': '60px', 'lineHeight': '60px',
            'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px',
            'textAlign': 'center', 'margin': '10px 0', 'cursor': 'pointer',
        },
        multiple=False
    ),
    dcc.Dropdown(
        id='value-dropdown',
        placeholder='Select a value...',
        style={'margin': '10px 0'}
    ),
    dls.Ring(
        html.Div(id='output-data-upload', style={'margin': '20px 0'}),
    ),
    html.A(
        className="github-fab",
        href="https://github.com/rdlxs/python_curso/tree/main/Ejemplos",
        target="_blank",
        children=html.I(className="fab fa-github fa-2x"),
        style={
            'position': 'fixed', 'bottom': '20px', 'right': '20px',
            'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center',
            'color': 'white', 'backgroundColor': '#000', 'borderRadius': '50%',
            'width': '50px', 'height': '50px', 'textAlign': 'center',
            'textDecoration': 'none', 'boxShadow': '2px 2px 3px rgba(0,0,0,0.2)',
        }
    ),
])

@app.callback(
    [Output('output-data-upload', 'children'),
     Output('value-dropdown', 'options')],
    [Input('upload-data', 'contents'),
     Input('value-dropdown', 'value')]
)
def update_output(list_of_contents, selected_value):
    print("Callback triggered")
    if list_of_contents:
        df, error_message = parse_contents(list_of_contents)
        if df is None:
            return html.Div(error_message, style={'color': 'red'}), []
        
        print("Dataframe loaded:", df.head())  # Imprime las primeras filas del DataFrame

        # Si hay columnas válidas para el dropdown
        valid_columns = [col for col in df.columns if df[col].dtype in ['float64', 'int64']]
        dropdown_options = [{'label': col, 'value': col} for col in valid_columns]

        # Si no hay ninguna opción válida, no se selecciona ninguna
        if selected_value and selected_value not in valid_columns:
            selected_value = valid_columns[0] if valid_columns else None

        # Verifica si existe Latitude y Longitude
        if 'Latitude' in df.columns and 'Longitude' in df.columns:
            # Mapa interactivo
            fig_map = px.scatter_map(df, lat='Latitude', lon='Longitude', color=selected_value,
                                     zoom=10, height=500, color_continuous_scale='Jet', hover_data=df.columns)
            fig_map.update_layout(map_style="open-street-map", margin={"r": 0, "t": 0, "l": 0, "b": 0})
            map_fig = dcc.Graph(id='map-plot', figure=fig_map)
        else:
            map_fig = html.Div("⚠️ El archivo no contiene columnas 'Latitude' y 'Longitude'. No se puede mostrar el mapa.",
                               style={'color': 'orange', 'marginBottom': '10px'})

        # Gráfico de serie temporal
        time_column = "Time" if "Time" in df.columns else None
        if time_column and selected_value:
            fig_time_series = px.line(df, x=time_column, y=selected_value, title=f'{selected_value} over Time')
            fig_time_series.update_traces(mode='lines')
            fig_time_series.update_layout(hovermode='closest')
        else:
            fig_time_series = None

        # Estadísticas
        statistics = {
            'Statistic': ['Average', 'Maximum', 'Minimum', 'Start', 'End',
                          '25th Percentile', 'Median', '75th Percentile', '90th Percentile'],
            'Value': [
                df[selected_value].mean(), df[selected_value].max(), df[selected_value].min(),
                df[selected_value].iloc[0], df[selected_value].iloc[-1],
                np.percentile(df[selected_value].dropna(), 25),
                np.percentile(df[selected_value].dropna(), 50),
                np.percentile(df[selected_value].dropna(), 75),
                np.percentile(df[selected_value].dropna(), 90)
            ]
        }

        stats_df = pd.DataFrame(statistics)

        return html.Div([
            map_fig,
            dcc.Graph(id='time-series', figure=fig_time_series),
            dash_table.DataTable(
                data=stats_df.to_dict('records'),
                columns=[{'id': c, 'name': c} for c in stats_df.columns],
                style_cell={'textAlign': 'left'},
                style_header={'backgroundColor': 'white', 'fontWeight': 'bold'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': 'rgb(248, 248, 248)'}
                ]
            )
        ]), dropdown_options

    return "No file uploaded.", []

if __name__ == '__main__':
    app.run(debug=False)
