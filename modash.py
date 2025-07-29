"""Experimental data visualization tool for MoSAIC tdms files."""

# TODO: Add radio button to normalize timestamps to zero. I'm envisioning this being
# used to compare traces across multiple files, so each channel/file combination would
# have a different color

# TODO: Add radio button to remove gaps in time between files. Timestamps would need to
# be normalized to zero and then annotations added to the chart

# TODO: Add feature to add dimension of test number from within MoSAIC TDMS files

# TODO: Add hover events to legend to highlight traces when you hover over their entries
# in the legend

# TODO: Add ability to add more than two y-axes

# TODO: Add ability to add stacked subplots

import json
import webbrowser
from pathlib import Path
from threading import Timer

import dash_bootstrap_components as dbc
import dash_uploader as du
import nptdms
import plotly.graph_objects as go
import polars as pl
from dash import Dash, Input, Output, State, callback, dash_table, dcc, html, no_update
from loguru import logger
from plotly.subplots import make_subplots

logger.add('logs/modash.log', rotation='10 MB', retention='90 days', colorize=False)

app = Dash(
    name='MoDash',
    title='MoDash',
    external_stylesheets=[dbc.themes.BOOTSTRAP],
)

UPLOAD_PATH = Path('./uploads/')
UPLOAD_PATH.mkdir(exist_ok=True)
# deleting all previous uploads
for item in sorted(UPLOAD_PATH.glob('**/*'), reverse=True):
    if item.is_file():
        item.unlink()
    if item.is_dir():
        item.rmdir()
du.configure_upload(app, folder=UPLOAD_PATH)

# TODO: create tabindex values for all of these components which require interaction so
# the user can tab between them easily

primary_dropdown = dcc.Dropdown(
    id='primary_dropdown',
    multi=True,
    clearable=True,
    searchable=True,
    placeholder='Type here to search, enter or tab to select',
    style={'margin-top': 5},
)

secondary_dropdown = dcc.Dropdown(
    id='secondary_dropdown',
    multi=True,
    clearable=True,
    searchable=True,
    placeholder='Type here to search, enter or tab to select',
    style={'margin-top': 5},
)

file_selection = du.Upload(
    max_file_size=500,
    max_files=15,
    filetypes=['tdms'],
    id='dash_uploader',
    text='Drag and drop files here or click to select files',
    default_style={'margin-bottom': 5},
)

file_list = dash_table.DataTable(
    id='file_list',
    data=None,
    columns=[{'name': 'Filenames', 'id': 'filename'}],
    row_deletable=True,
    style_cell={'textAlign': 'left'},
)

data_mgmt_button = dbc.Button(
    'Data Management', outline=True, color='primary', id='data_mgmt_button'
)

new_tab_button = dbc.Button(
    'New MoDash Tab',
    outline=True,
    color='success',
    id='new_tab_button',
    style={'margin-left': 5},
)

# This button's style is set to 'none' so it doesn't appear in the layout. It's meant to
# be hidden and only exists to interact with the dash callback to shutdown the server
shutdown_button = html.Button(id='shutdown_button', style={'display': 'none'})


data_mgmt_canvas = dbc.Offcanvas(
    [
        dbc.Row(
            [
                dbc.Col(
                    [
                        file_selection,
                        file_list,
                        dbc.Alert(
                            [html.Div('Primary Axis:'), primary_dropdown],
                            style={'margin-top': 5, 'margin-bottom': 0},
                        ),
                        dbc.Alert(
                            [html.Div('Secondary Axis:'), secondary_dropdown],
                            style={'margin-top': 5, 'margin-bottom': 0},
                        ),
                    ]
                )
            ]
        )
    ],
    is_open=True,
    close_button=False,
    id='data_mgmt_canvas',
)

tdms_graph = dcc.Graph(
    id='tdms_graph',
    config={
        'autosizable': False,
        'fillFrame': True,
        'editable': True,
        'edits': {'titleText': False},
        'doubleClick': 'reset+autosize',
        'showLink': True,
        'frameMargins': 10,
    },
)

app.layout = dbc.Container(
    fluid=True,
    children=[
        dbc.Row(
            [
                dbc.Col(
                    [data_mgmt_button, new_tab_button, shutdown_button, tdms_graph],
                    width='auto',
                    style={'margin-top': 5},
                ),
            ]
        ),
        data_mgmt_canvas,
        dcc.Store(id='paths_store'),
    ],
)


@callback(
    Output(data_mgmt_canvas.id, 'is_open'),
    Input(data_mgmt_button.id, 'n_clicks'),
    State(data_mgmt_canvas.id, 'is_open'),
)
def toggle_data_mgmt_canvas(
    n_clicks: int,
    is_open: bool,
):
    """Callback to open data management canvas if it is closed.

    Args:
        n_clicks (int): number of times the data management button has been clicked
        is_open (bool): whether or not the data management canvas is open

    Returns:
        bool: indicates new status of data management canvas
        no_update: will return without updating status of outputs
    """
    logger.info('Data management canvas opened.')
    if n_clicks:
        return not is_open
    return no_update


@du.callback(
    [
        Output(primary_dropdown.id, 'options'),
        Output(secondary_dropdown.id, 'options'),
        Output('paths_store', 'data'),
    ],
    id=file_selection.id,
)
def on_upload(status: du.UploadStatus):
    """Populates files and channels lists with data from tdms files.

    Args:
        status (dash_uploader.UploadStatus): object which contains various pieces of
            information about the upload progress and status when complete

    Returns:
        tuple of length 3:
            list[str]: list of strings representing channels found in the tdms files to
                populate the primary axis dropdown menu
            list[str]: same but for the secondary axis dropdown menu
            str: list of paths to the uploaded files but serialized into json so it can
                be put into a server-side data store

    """
    # TODO: Add ability to also handle and concatenate CSV files
    if status.is_completed and status.n_uploaded > 0:
        logger.info(f'New files uploaded. Uploader status: {status}')
        files_to_add = json.dumps([str(path) for path in status.uploaded_files])
        all_channels = set()
        for tdms_path in status.uploaded_files:
            tdms = nptdms.TdmsFile.open(tdms_path)
            channels = [channel.name for channel in tdms['RTAC Data'].channels()]
            all_channels.update(channels)
        all_channels = list(all_channels)
        logger.info(f'Channels discovered in tdms files: {all_channels}')
        return (
            all_channels,
            all_channels,
            files_to_add,
        )
    return no_update


@callback(
    Output(file_list.id, 'data'),
    Input('paths_store', 'data'),
    State(file_list.id, 'data'),
    prevent_initial_call=True,
)
def on_add_files(new_paths_json: str, current_rows: list[dict]):
    """Updates file list when new files are uploaded.

    Fires when paths are added to the data store by the "on_upload" method. This chained
    callback using a data store is required because the special callback provided by the
    dash_uploader library doesn't allow you to pass State objects into it, so the
    callback can't get the current list of files to modify.

    Args:
        new_paths_json (str): json serialized list of paths to newly uploaded files
        current_rows (list[dict]): list of rows currently in the files list already.
            Each item has the format:
                {
                    'filename': <string containing just the filename>,
                    'id': <string to full path of uploaded file>
                }

    Returns:
        List formatted in the same way as the "current_rows" argument containing the new
            list of files
    """
    new_paths = [Path(path) for path in json.loads(new_paths_json)]
    new_rows = [{'filename': path.name, 'id': str(path)} for path in new_paths]
    if current_rows:
        for row in new_rows:
            if row not in current_rows:
                current_rows.append(row)

        rows = sorted(current_rows, key=lambda row: row['filename'])
        logger.info(f'New files list: {rows}')
        return rows
    rows = sorted(new_rows, key=lambda row: row['filename'])
    logger.info(f'New files list: {rows}')
    return rows


@callback(
    Output(tdms_graph.id, 'figure'),
    Input(data_mgmt_canvas.id, 'is_open'),
    State(file_list.id, 'data'),
    State(primary_dropdown.id, 'value'),
    State(secondary_dropdown.id, 'value'),
)
def on_canvas_close(
    canvas_open: bool,
    file_list_rows: list[dict] | None,
    prim_channels: list[str] | None,
    sec_channels: list[str] | None,
):
    """Processes tdms files and channels lists to create figure.

    This callback does the heavy lifting of reading the tdms files, aligning the
    timestamps, building the polars dataframe, and plotting each individual trace

    Args:
        canvas_open (bool): current state of data management canvas. Function will
            immediately return if the canvas was just opened instead of closed.
        file_list_rows (list[dict] | None): list of rows currently in the files list.
            Each item has the format:
                {
                    'filename': <string containing just the filename>,
                    'id': <string to full path of uploaded file>
                }
            Value of this argument can also sometimes be None if the element has not
            been interacted with by the user yet
        prim_channels (list[str]): list of channels in the primary axis dropdown menu.
            Value of this argument can also sometimes be None if the element has not
            been interacted with by the user yet
        sec_channels (list[str]): list of channels in the secondary axis dropdown menu.
            Value of this argument can also sometimes be None if the element has not
            been interacted with by the user yet

    Returns:
        plotly.graph_objects.Figure: plotly figure object to populate the main panel of
            the app when the data management canvas is closed
    """
    # TODO: If people start using this for truly HUGE tdms files, it may becomes
    # necessary to figure out a way for the dataframe to persist outside of the scope of
    # this callback. This would allow this callback to essentially "cache" partial data
    # and if a single channel is added or removed, all the other channels wouldn't have
    # to be reloaded. I would consider duckdb for this, I think.
    # TODO: integrate spinner
    if canvas_open:
        return no_update
    logger.info('Data management canvas closed.')
    if not (prim_channels or sec_channels):
        logger.info('No data to plot, no channels selected.')
        return
    if not file_list_rows:
        logger.info('No data to plot, no files selected.')
        return
    if prim_channels is None:
        prim_channels = []
    if sec_channels is None:
        sec_channels = []
    logger.info(f'Files selected: {file_list_rows}')
    logger.info(f'Primary channels selected: {prim_channels}')
    logger.info(f'Secondary channels selected: {sec_channels}')
    tdms_paths = [Path(row['id']) for row in file_list_rows]
    dfs = []
    for tdms_path in tdms_paths:
        with nptdms.TdmsFile.open(tdms_path) as tdms:
            data_by_timestamp = {
                timestamp.name: pl.DataFrame(
                    # timestamp data
                    {
                        'datetime': pl.from_numpy(
                            timestamp.read_data(), schema={'datetime': pl.Datetime}
                        )
                    }
                    # union with another dictionary with the channel data
                    | {
                        # channel data
                        # TODO: verify that this operation is only performed if the if
                        # condition at the end of dict comprehension is True
                        channel_name: pl.from_numpy(
                            tdms['RTAC Data'][channel_name].read_data()
                        )
                        # for each unique channel name in the selected channels
                        for channel_name in set(prim_channels + sec_channels)
                        # but only if the channel is associated with the right timestamp
                        if tdms['RTAC Data'][channel_name]
                        .properties['Xaxis']
                        .split('/')[1]
                        == timestamp.name
                    }
                )  # .with_columns(filename=pl.lit(tdms_path.name))
                # iterates over each timestamp in the file
                for timestamp in tdms['TimeStamps'].channels()
            }

        # Iteratively merging all dataframes based on datetime. The result of this is
        # that all channels will have a common time axis, but channels with timestamps
        # of lower acquisition frequency than the maximum in the tdms file will have
        # blank values.
        right = pl.DataFrame(schema={'datetime': pl.Datetime})
        for left in data_by_timestamp.values():
            right = right.join(left, on='datetime', how='full', coalesce=True)
        dfs.append(right)
    df = pl.concat(dfs, how='diagonal_relaxed').sort('datetime')
    fig = make_subplots(specs=[[{'secondary_y': True}]])
    fig.update_layout(
        margin={'r': 0, 'l': 50, 't': 30, 'b': 125},
        legend={
            'orientation': 'v',
            'x': 0.01,
            'y': 0.99,
            'xanchor': 'left',
            'yanchor': 'top',
            'bgcolor': 'rgba(255,255,255,0.5)',
        },
        xaxis={
            'title': 'Date & Time',
            'spikemode': 'across',
            'spikesnap': 'cursor',
            'spikethickness': 1,
            'spikecolor': 'black',
        },
        yaxis={
            'spikemode': 'across',
            'spikesnap': 'cursor',
            'spikethickness': 0.5,
            'spikecolor': 'black',
        },
        yaxis2={
            'spikemode': 'across',
            'spikesnap': 'cursor',
            'spikethickness': 0.5,
            'spikecolor': 'black',
        },
    )
    for channels, secondary_y in [(prim_channels, False), (sec_channels, True)]:
        for channel in channels:
            fig.add_trace(
                go.Scatter(
                    x=df['datetime'],
                    y=df[channel],
                    mode='lines',
                    name=channel + (' (secondary)' if secondary_y else ' (primary)'),
                    connectgaps=True,
                    showlegend=True,
                ),
                secondary_y=secondary_y,
            )
    return fig


@callback(Input(new_tab_button.id, 'n_clicks'))
def on_new_tab(_):
    """Opens new browser tab and increments client count."""
    logger.info('New tab button clicked.')
    global active_clients
    active_clients += 1
    logger.info(f'Active clients: {active_clients}')
    webbrowser.open_new(f'http://{HOST}:{PORT}/')


@callback(Input(shutdown_button.id, 'n_clicks'), prevent_initial_call=True)
def shutdown(_):
    """Shuts down dash server when last browser tab is closed.

    In /assets/ there is a javascript function which adds an event listener to the
    window to listen for the 'beforeunload' event which is fired right before a tab is
    closed. The function then interacts with the document to click the hidden
    'shutdown_button' which runs the code below to terminate the process running the
    server running this app when the last tab (tracked by the active_clients global
    variable) has been closed. This behavior isn't super consistent, so I've disabled at
    least the shutdown portion of this. Active clients will still be tracked. The
    inconsistent behavior might be related to me using a *gasp* global variable.
    """
    # TODO: migrate away from a global variable for this. See docstring.
    logger.info('Browser tab closed.')
    global active_clients
    active_clients -= 1
    logger.info(f'Active clients: {active_clients}')


#     if active_clients < 1:
#         logger.info('No more client connections. Shutting down server.')
#         os.kill(os.getpid(), signal.SIGTERM)


def open_first_tab():
    """Called to open the first tab (client) of the app."""
    # TODO: I know this is bad practice, but it should work as long as there's only one
    # server running and the user only uses the button to open new tabs (instead of
    # opening a new tab manually).
    logger.info('New app init.')
    global active_clients
    active_clients = 1
    Timer(
        interval=0.5, function=webbrowser.open_new, args=[f'http://{HOST}:{PORT}/']
    ).start()
    logger.info(f'Active clients: {active_clients}')


if __name__ == '__main__':
    HOST = '127.0.0.1'
    PORT = 8050
    open_first_tab()
    app.run(host=HOST, port=PORT, debug=True, use_reloader=False)
