import base64
import io
import pandas as pd
import plotly.express as px
from dash import Dash, html, dcc, Input, Output, State, callback_context
from dash import dash_table
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

        print("Dataframe loaded:")
        print(df.columns)
        print(df.head())

        valid_columns = [col for col in df.columns if df[col].dtype in ['float64', 'int64']]
        dropdown_options = [{'label': col, 'value': col} for col in valid_columns]

        if selected_value is None and valid_columns:
            selected_value = valid_columns[0]

        time_column = "Time" if "Time" in df.columns else None

        # --- MAPA ---
        if 'Latitude' in df.columns and 'Longitude' in df.columns and selected_value:
            if any(df[selected_value] < 0) and any(df[selected_value] > 0):
                color_scale = px.colors.sequential.RdBu
                midpoint = 0
            else:
                color_scale = px.colors.sequential.Jet
                midpoint = None

            fig_map = px.scatter_map(
                df,
                lat='Latitude',
                lon='Longitude',
            color=selected_value,
            zoom=10,
            height=500,
            color_continuous_scale=color_scale,
            color_continuous_midpoint=midpoint,
            hover_data=df.columns
            )
            fig_map.update_layout(map_style="open-street-map", margin={"r": 0, "t": 0, "l": 0, "b": 0})

        else:
            map_fig = html.Div("⚠️ No se puede mostrar el mapa. Verificá que existan columnas 'Latitude', 'Longitude' y que se haya seleccionado una métrica.",
                               style={'color': 'orange'})

        # --- GRAFICO TEMPORAL ---
        if time_column and selected_value:
            df_cleaned = df.dropna(subset=[selected_value])
            fig_time_series = px.line(df_cleaned, x=time_column, y=selected_value, title=f'{selected_value} over Time')
            fig_time_series.update_traces(mode='lines')
            fig_time_series.update_layout(hovermode='closest')
        else:
            fig_time_series = None

        # --- ESTADISTICAS ---
        if selected_value:
            col_data = df[selected_value].dropna()
            stats = {
                'Statistic': ['Average', 'Maximum', 'Minimum', 'Start', 'End',
                              '25th Percentile', 'Median', '75th Percentile', '90th Percentile'],
                'Value': [
                    col_data.mean(), col_data.max(), col_data.min(),
                    col_data.iloc[0], col_data.iloc[-1],
                    np.percentile(col_data, 25),
                    np.percentile(col_data, 50),
                    np.percentile(col_data, 75),
                    np.percentile(col_data, 90)
                ]
            }
            stats_df = pd.DataFrame(stats)
            stats_table = dash_table.DataTable(
                data=stats_df.to_dict('records'),
                columns=[{'id': c, 'name': c} for c in stats_df.columns],
                style_cell={'textAlign': 'left'},
                style_header={'backgroundColor': 'white', 'fontWeight': 'bold'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': 'rgb(248, 248, 248)'}
                ],
                style_table={'height': '350px', 'overflowY': 'auto'},
            )
        else:
            stats_table = html.Div("No se pudo calcular estadísticas.", style={'color': 'orange'})

        return html.Div([
            map_fig,
            dcc.Graph(id='time-series', figure=fig_time_series),
            stats_table
        ]), dropdown_options

    return html.Div('Please upload a CSV file.'), []

if __name__ == '__main__':
    app.run(debug=True)
