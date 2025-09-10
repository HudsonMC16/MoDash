"""Experimental data visualization tool for MoSAIC tdms files."""

# NOTE: Implementing many of the features below would probably be best in a separate
# canvas accessed via a "GUI Management" or "Viz Management" button. I'm thinking there
# is a radio button which controls how separate files are handled:
# - Same axes, actual timestamps
# - Facet plots (side-by-side or stacked)
# - Same axes, normalized timestamps:
#       - all files normalized to zero with different color traces for each file...
#       - files concatenated with vlines at file boundaries

# TODO: add button to save options and possibly channel selections as defaults or even
# to a file so they can be recalled later

# TODO: Add feature to add dimension of test number from within MoSAIC TDMS files

# TODO: Add hover events to legend to highlight traces when you hover over their entries
# in the legend

# TODO: Add ability to add more than two y-axes

# TODO: Update README to include explanation of resampling features

import json
import webbrowser
from datetime import datetime as dt
from pathlib import Path
from threading import Timer

import dash_bootstrap_components as dbc
import dash_uploader as du
import nptdms
import plotly.graph_objects as go
import polars as pl
from dash_extensions.enrich import (
    DashProxy,
    Input,
    Output,
    Serverside,
    ServersideOutputTransform,
    State,
    callback,
    dash_table,
    dcc,
    html,
    no_update,
)
from loguru import logger
from plotly.subplots import make_subplots
from plotly_resampler import FigureResampler

logger.add('logs/modash.log', rotation='10 MB', retention='90 days', colorize=False)

app = DashProxy(
    name='MoDash',
    title='MoDash',
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    transforms=[ServersideOutputTransform()],
)

UPLOAD_PATH = Path('./uploads/')
UPLOAD_PATH.mkdir(exist_ok=True)
CACHE_PATH = Path('./file_system_backend/')

# deleting all previous uploads and cache
for path in [UPLOAD_PATH, CACHE_PATH]:
    for item in sorted(path.glob('**/*'), reverse=True):
        if item.is_file():
            item.unlink()
        if item.is_dir():
            item.rmdir()
du.configure_upload(app, folder=UPLOAD_PATH)

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
    max_file_size=1500,
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

data_mgmt_canvas_button = dbc.Button(
    'Data Management', outline=True, color='primary', id='data_mgmt_canvas_button'
)

new_tab_button = dbc.Button(
    'New MoDash Tab',
    outline=True,
    color='success',
    id='new_tab_button',
    style={'margin-left': 5},
)

export_canvas_button = dbc.Button(
    'Export Plot',
    outline=True,
    color='info',
    id='export_canvas_button',
    style={'margin-left': 5},
)
export_filename_input = dbc.Input(
    id='export_filename_input',
    debounce=True,
    persistence=True,
    persistence_type='local',
    value='MoDash-<fdt>',
)
export_width_input = dbc.Input(
    id='export_width_input',
    debounce=True,
    persistence=True,
    persistence_type='local',
    value=1200,
    type='number',
    step=1,
    required=True,
    min=1,
    max=4096,
)
export_height_input = dbc.Input(
    id='export_height_input',
    debounce=True,
    persistence=True,
    persistence_type='local',
    value=800,
    type='number',
    step=1,
    required=True,
    min=1,
    max=2160,
)
export_interactive_button = dbc.Button(
    'Export Interactive Plot',
    outline=True,
    color='info',
    id='export_interactive_button',
    # style={'margin-left': 5},
)
export_image_button = dbc.Button(
    'Export Image',
    outline=True,
    color='info',
    id='export_image_button',
    # style={'margin-left': 5},
)
plotly_js_radio = dbc.RadioItems(
    {
        'include': 'Include within every exported html file. Adds ≈4-5 MB to each file.',
        'directory': 'Inlcude as separate "plotly.min.js" file in the export directory, if it does not already exist.',
        'cdn': 'Use content delivery network to download latest Plotly javascript when file is opened. Requires network access to open files, but underlying chart data is not sent over the network',
    },
    label_style={'margin-bottom': '5px'},
    persistence=True,
    persistence_type='local',
    value='directory',
    id='plotly_js_radio',
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

export_canvas = dbc.Offcanvas(
    [
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Alert(
                            [
                                html.Div('Export Filename:'),
                                export_filename_input,
                            ],
                            style={'margin-top': 0, 'margin-bottom': 5},
                            color='info',
                        ),
                        dbc.Alert(
                            [
                                html.Div('Exported image width and height (pixels):'),
                                dbc.Row(
                                    [
                                        dbc.Col(export_width_input),
                                        dbc.Col(export_height_input),
                                    ]
                                ),
                            ],
                            style={'margin-top': 0, 'margin-bottom': 5},
                            color='info',
                        ),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dcc.Loading(
                                        [
                                            export_interactive_button,
                                            dcc.Download(id='fig_html_download'),
                                        ]
                                    ),
                                    width=6,
                                    align='stretch',
                                ),
                                dbc.Col(
                                    dcc.Loading(
                                        [
                                            export_image_button,
                                            dcc.Download(id='fig_image_download'),
                                        ]
                                    ),
                                    width=6,
                                    align='stretch',
                                ),
                            ]
                        ),
                        dbc.Alert(
                            [
                                html.H6('Available placeholders for filenames:'),
                                html.Div('<dt> : Current datetime'),
                                html.Div('<d> : Current date'),
                                html.Div('<t> : Current clock time (24 hr)'),
                                html.Div(
                                    '<fdt> : Datetime of earliest timestamp in chart data'
                                ),
                                html.Div(
                                    '<fd> : Date of earliest timestamp in chart data'
                                ),
                                html.Div(
                                    '<ft> : Clock time (24 hr) of earliest timestamp in chart data'
                                ),
                            ],
                            color='warning',
                            style={'margin-top': 5, 'margin-bottom': 0},
                        ),
                        dbc.Alert(
                            [
                                html.Div(
                                    'Images will be exported as png files and interactive plots will be exported as html files.'
                                ),
                            ],
                            color='warning',
                            style={'margin-top': 5, 'margin-bottom': 0},
                        ),
                        dbc.Alert(
                            [
                                html.H6('Interactive Plotly Javascript Handling:'),
                                plotly_js_radio,
                            ],
                            color='success',
                            style={'margin-top': 5},
                        ),
                    ]
                )
            ]
        )
    ],
    is_open=False,
    close_button=False,
    id='export_canvas',
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
                    [
                        data_mgmt_canvas_button,
                        new_tab_button,
                        export_canvas_button,
                        shutdown_button,
                        dcc.Loading(tdms_graph),
                    ],
                    width='auto',
                    style={'margin-top': 5},
                ),
            ]
        ),
        data_mgmt_canvas,
        export_canvas,
        dcc.Store(id='paths_store'),
        dcc.Store(id='timestamp_store'),
        dcc.Store(id='figure_cache'),
    ],
)


@callback(
    Output(data_mgmt_canvas.id, 'is_open'),
    Input(data_mgmt_canvas_button.id, 'n_clicks'),
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


@callback(
    Output(export_canvas.id, 'is_open'),
    Input(export_canvas_button.id, 'n_clicks'),
    State(export_canvas.id, 'is_open'),
    prevent_initial_call=True,
)
def toggle_export_canvas(
    n_clicks: int,
    is_open: bool,
):
    """Callback to open export canvas if it is closed.

    Args:
        n_clicks (int): number of times the export button has been clicked
        is_open (bool): whether or not the export canvas is open

    Returns:
        bool: indicates new status of export canvas
        no_update: will return without updating status of outputs
    """
    logger.info('Export canvas opened.')
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
    Output('figure_cache', 'data'),
    Output('timestamp_store', 'data'),
    Input(data_mgmt_canvas.id, 'is_open'),
    State(file_list.id, 'data'),
    State(primary_dropdown.id, 'value'),
    State(secondary_dropdown.id, 'value'),
)
def on_data_canvas_close(
    canvas_open: bool,
    file_list_rows: list[dict] | None,
    prim_channels: list[str] | None,
    sec_channels: list[str] | None,
) -> tuple[dict, FigureResampler, str] | type[no_update]:
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
        return no_update
    if not file_list_rows:
        logger.info('No data to plot, no files selected.')
        return no_update
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
    df: pl.DataFrame = pl.concat(dfs, how='diagonal_relaxed').sort('datetime')
    first_timestamp = df['datetime'].min()
    fdt = {
        'fdt': first_timestamp.strftime('%Y%m%dT%H%M%S'),
        'fd': first_timestamp.date().strftime('%Y%m%d'),
        'ft': first_timestamp.time().strftime('T%H%M%S'),
    }

    fig = FigureResampler(make_subplots(specs=[[{'secondary_y': True}]]))
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
            'tickmode': 'sync',
        },
    )
    for channels, secondary_y in [(prim_channels, False), (sec_channels, True)]:
        for channel in channels:
            fig.add_trace(
                go.Scattergl(
                    # Converting all these to lists because if they remain as polars
                    # series (or any rich data type) when this callback is complete and
                    # the figure is serialized to json, the metadata of the richer data
                    # type will be saved alongside the actual data in the json,
                    # ballooning the size on disk, and therefore the export size. It
                    # also affects performance.
                    # x=df['datetime'].to_list(),
                    # y=df[channel].to_list(),
                    mode='lines',
                    name=channel + (' (secondary)' if secondary_y else ' (primary)'),
                    connectgaps=True,
                    showlegend=True,
                ),
                secondary_y=secondary_y,
                hf_x=df['datetime'].to_numpy(),
                hf_y=df[channel].to_numpy(),
                max_n_samples=3000,
            )
    return fig, Serverside(fig), json.dumps(fdt)


@callback(
    Output(tdms_graph.id, 'figure', allow_duplicate=True),
    Input(tdms_graph.id, 'relayoutData'),
    State('figure_cache', 'data'),
    prevent_initial_call=True,
    memoize=True,
)
def resample_fig(relayoutdata: dict, fig: FigureResampler):
    """Just handles resampling the figure data when it's zoomed or panned."""
    if fig is None:
        return no_update
    return fig.construct_update_data_patch(relayoutdata)


@callback(Input(new_tab_button.id, 'n_clicks'))
def on_new_tab(_):
    """Opens new browser tab and increments client count."""
    logger.info('New tab button clicked.')
    global active_clients
    active_clients += 1
    logger.info(f'Active clients: {active_clients}')
    webbrowser.open_new(f'http://{HOST}:{PORT}/')


@callback(
    Output('fig_html_download', 'data'),
    Input(export_interactive_button.id, 'n_clicks'),
    State('figure_cache', 'data'),
    State(export_filename_input.id, 'value'),
    State(plotly_js_radio.id, 'value'),
    State('timestamp_store', 'data'),
    prevent_initial_call=True,
)
def on_export_interactive(
    _,
    fig: FigureResampler,
    filename_raw: str,
    plotlyjs_select: str,
    ts_json: str,
) -> dict:
    """Passes current figure html as dictionary to download component.

    Args:
        fig (FigureResampler): cached resampled figure object
        filename_raw (str): string user has entered into the filename input box,
            including any placeholders
        plotlyjs_select (str): selection user has made with the plotlyjs radio buttons
        ts_json (str): json formatted string containing information about the earliest
            timestamp in the chart data

    Returns:
        Dictionary formatted in the way the download component expects which contains
            plotly figure html representation.
    """
    logger.info('Export interactive button clicked.')
    plotlyjs = True if plotlyjs_select == 'include' else plotlyjs_select
    now = dt.now()
    ts_dict = json.loads(ts_json)
    filename = (
        filename_raw.replace('<dt>', now.strftime('%Y%m%dT%H%M%S'))
        .replace('<t>', now.time().strftime('T%H%M%S'))
        .replace('<d>', now.date().strftime('%Y%m%d'))
        .replace('<fdt>', ts_dict['fdt'])
        .replace('<fd>', ts_dict['fd'])
        .replace('<ft>', ts_dict['ft'])
    ) + '.html'
    return dcc.send_string(
        fig.to_html(include_plotlyjs=plotlyjs),
        filename=filename,
        type='text/html',
    )


@callback(
    Output('fig_image_download', 'data'),
    Input(export_image_button.id, 'n_clicks'),
    State(tdms_graph.id, 'figure'),
    State(export_filename_input.id, 'value'),
    State('timestamp_store', 'data'),
    State(export_width_input.id, 'value'),
    State(export_height_input.id, 'value'),
    prevent_initial_call=True,
)
def on_export_image(
    _,
    fig_dict: dict,
    filename_raw: str,
    ts_json: str,
    image_width: str,
    image_height: str,
) -> dict:
    """Passes current figure image as dictionary to download component.

    Args:
        fig (FigureResampler): cached resampled figure object
        filename_raw (str): string user has entered into the filename input box,
            including any placeholders
        ts_json (str): json formatted string containing information about the earliest
            timestamp in the chart data
        image_width (str): value user has input for desired width in pixels of exported
            images
        image_height (str): value user has input for desired height in pixels of exported
            images

    Returns:
        Dictionary formatted in the way the download component expects which contains
            plotly figure image representation.
    """
    logger.info('Export interactive button clicked.')
    now = dt.now()
    ts_dict = json.loads(ts_json)
    filename = (
        filename_raw.replace('<dt>', now.strftime('%Y%m%dT%H%M%S'))
        .replace('<t>', now.time().strftime('T%H%M%S'))
        .replace('<d>', now.date().strftime('%Y%m%d'))
        .replace('<fdt>', ts_dict['fdt'])
        .replace('<fd>', ts_dict['fd'])
        .replace('<ft>', ts_dict['ft'])
    ) + '.png'
    return dcc.send_bytes(
        go.Figure(fig_dict).to_image(
            format='png', width=image_width, height=image_height
        ),
        filename=filename,
        type='image/png',
    )


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
