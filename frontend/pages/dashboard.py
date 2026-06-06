"""
frontend/pages/dashboard.py
---------------------------
Dashboard view showing onboarding state and details.
Pure NiceGUI — no raw HTML inputs or JavaScript.
"""

from datetime import datetime
from nicegui import app, ui
from frontend.logo import LOGO_32

# Backend service integrations
from backend.pipeline_service import get_user_source_files, start_pipeline, get_execution_status, get_execution_logs
from backend.schema_service import get_schema_options, get_user_schema_selection, update_user_schema_selection
from backend.database import get_username_by_id
import config


def format_size(size_bytes: int) -> str:
    """Format file size in bytes to a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_date(iso_str: str) -> str:
    """Format ISO timestamp to standard format."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str


def get_user_output_files(user_id: int) -> list:
    """List generated files in user's isolated outputs folder."""
    try:
        username = get_username_by_id(user_id)
    except Exception:
        return []
    outputs_dir = config.WORKSPACES_DIR / "users" / username / "outputs"
    if not outputs_dir.exists() or not outputs_dir.is_dir():
        return []
    
    files_list = []
    for p in outputs_dir.iterdir():
        if p.is_file():
            stat_info = p.stat()
            modified_time = datetime.fromtimestamp(stat_info.st_mtime).isoformat()
            files_list.append({
                "name": p.name,
                "size": stat_info.st_size,
                "modified": modified_time
            })
    return sorted(files_list, key=lambda x: x["name"])


@ui.page('/')
def dashboard_page():
    username = app.storage.user.get('username', 'Guest')
    user_id = app.storage.user.get('user_id', 1)  # Graceful fallback to user_id=1 if session unset

    ui.add_head_html('''
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
      body { font-family: 'Inter', sans-serif !important; background-color: #f8fafc !important; color: #1e293b; }
      
      /* Custom scrollbar for the scrollable container */
      .custom-scroll {
        overflow-y: scroll !important;
        overflow-x: hidden !important;
      }
      .custom-scroll::-webkit-scrollbar {
        width: 6px;
      }
      .custom-scroll::-webkit-scrollbar-track {
        background: transparent;
      }
      .custom-scroll::-webkit-scrollbar-thumb {
        background: #cbd5e1; /* slate-300 */
        border-radius: 3px;
      }
      .custom-scroll::-webkit-scrollbar-thumb:hover {
        background: #94a3b8; /* slate-400 */
      }

      /* Custom scrollbar for the dark terminal console */
      .terminal-scroll::-webkit-scrollbar {
        width: 6px;
      }
      .terminal-scroll::-webkit-scrollbar-track {
        background: #0f172a;
      }
      .terminal-scroll::-webkit-scrollbar-thumb {
        background: #334155; /* slate-700 */
        border-radius: 3px;
      }
      .terminal-scroll::-webkit-scrollbar-thumb:hover {
        background: #475569; /* slate-600 */
      }
    </style>
    ''')

    def handle_logout():
        app.storage.user.clear()
        ui.navigate.to('/login')

    # ── Header bar ───────────────────────────────────────────────────────────
    with ui.row().classes('w-full items-center justify-between q-pa-md bg-white').style(
        'border-bottom: 1px solid #e2e8f0; position: sticky; top: 0; z-index: 10;'
    ):
        with ui.row().classes('items-center gap-2'):
            ui.html(LOGO_32)
            ui.html(
                '<span style="font-size:1.1rem;font-weight:700;color:#0f172a;letter-spacing:-0.3px;">'
                'Onboard<span style="color:#2563eb;">IQ</span></span>'
            )
            ui.html(
                '<span style="font-size:0.7rem;font-weight:600;color:#2563eb;background:#eff6ff;'
                'border:1px solid #bfdbfe;border-radius:20px;padding:2px 8px;">v1.0</span>'
            )

        with ui.row().classes('items-center q-gutter-md'):
            ui.label(f'Logged in as: {username}') \
              .classes('text-body2 text-weight-medium') \
              .style('color: #334155;')
            ui.button('Logout', on_click=handle_logout) \
              .props('flat dense icon=logout') \
              .style('color: #ef4444; font-weight: 600;')

    # ── Main content ─────────────────────────────────────────────────────────
    with ui.row().classes('w-full no-wrap q-pa-md gap-6').style('height: calc(100vh - 130px); min-height: 580px;'):
        # LEFT Panel: Workspace Explorer
        with ui.column().classes('col-3').style('min-width: 260px; height: 100%; min-height: 0;'):
            with ui.card().classes('q-pa-lg bg-white w-full no-wrap').style(
                'border: 1px solid #e2e8f0; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.04); height: 100%; display: flex; flex-direction: column; overflow: hidden; min-height: 0;'
            ):
                ui.label('Workspace Explorer') \
                  .classes('text-h6 text-weight-bold q-mb-xs') \
                  .style('color: #0f172a;')
                ui.label('Manage inputs, outputs, and schema.') \
                  .classes('text-caption q-mb-sm') \
                  .style('color: #64748b;')

                ui.separator().classes('q-mb-sm')

                # Scrollable area for workspace sections (folders & schema dropdown)
                with ui.column().classes('w-full custom-scroll p-1').style('flex: 1 1 0%; min-height: 0; overflow-y: scroll;'):
                    with ui.column().classes('w-full gap-2').style('min-height: calc(100% + 8px);'):

                        # 1. Target Schema Selection
                        with ui.column().classes('w-full gap-2 q-mb-sm'):
                            try:
                                schema_options = get_schema_options()
                                current_schema = get_user_schema_selection(user_id)
                            except Exception as e:
                                schema_options = []
                                current_schema = None
                                print(f"Error loading target schema list: {e}")
                            
                            def save_schema():
                                selected = schema_dropdown.value
                                if not selected:
                                    ui.notify('Please select a schema first', type='warning')
                                    return
                                try:
                                    success = update_user_schema_selection(user_id, selected)
                                    if success:
                                        ui.notify(f'Schema updated to {selected}', type='positive')
                                    else:
                                        ui.notify('Failed to save schema selection', type='negative')
                                except Exception as ex:
                                    ui.notify(f'Error: {str(ex)}', type='negative')

                            # Compact inline select & save row
                            with ui.row().classes('w-full items-center gap-2 no-wrap'):
                                schema_dropdown = ui.select(
                                    options=schema_options,
                                    value=current_schema,
                                    label='Target Schema'
                                ).classes('col-grow').props('outlined dense')

                                ui.button(on_click=save_schema, icon='save') \
                                  .props('unelevated dense') \
                                  .classes('text-white') \
                                  .style('background: #2563eb; border-radius: 6px; width: 40px; height: 40px;')

                        ui.separator().classes('q-my-sm')

                        # 2. Source Files (Input Data) - Collapsable Folder
                        with ui.expansion('Source Files', icon='folder', value=True) \
                                .classes('w-full') \
                                .props('dense') \
                                .style('color: #0f172a; font-weight: 600; font-size: 0.88rem;') as source_folder:
                            source_container = ui.column().classes('w-full gap-1 q-mt-xs')

                            def refresh_files():
                                source_container.clear()
                                try:
                                    files = get_user_source_files(user_id)
                                except Exception as e:
                                    files = []
                                    print(f"Error loading source files: {e}")

                                if not files:
                                    with source_container:
                                        ui.label('No input files uploaded.').classes('text-caption text-grey-5')
                                else:
                                    with source_container:
                                        for f in files:
                                            with ui.row().classes('w-full items-center justify-between no-wrap p-1 border-b border-slate-50 hover:bg-slate-50 rounded'):
                                                with ui.column().classes('col-grow gap-0'):
                                                    ui.label(f['name']).classes('text-xs text-weight-medium text-slate-800 truncate')
                                                    ui.label(f"{format_size(f['size'])} • {format_date(f['modified'])}").classes('text-caption text-grey-4')
                                                ui.icon('insert_drive_file').classes('text-slate-400').style('font-size: 14px;')

                            refresh_files()

                        ui.separator().classes('q-my-sm')

                        # 3. Output Files (Pipeline Results) - Collapsable Folder
                        with ui.expansion('Output Files', icon='folder', value=False) \
                                .classes('w-full') \
                                .props('dense') \
                                .style('color: #0f172a; font-weight: 600; font-size: 0.88rem;') as output_folder:
                            output_container = ui.column().classes('w-full gap-1 q-mt-xs')

                            def refresh_outputs():
                                output_container.clear()
                                try:
                                    files = get_user_output_files(user_id)
                                except Exception as e:
                                    files = []
                                    print(f"Error loading output files: {e}")

                                if not files:
                                    with output_container:
                                        ui.label('No executions yet').classes('text-caption text-grey-5')
                                else:
                                    with output_container:
                                        for f in files:
                                            with ui.row().classes('w-full items-center justify-between no-wrap p-1 border-b border-slate-50 hover:bg-slate-50 rounded'):
                                                with ui.column().classes('col-grow gap-0'):
                                                    ui.label(f['name']).classes('text-xs text-weight-medium text-slate-800 truncate')
                                                    ui.label(f"{format_size(f['size'])} • {format_date(f['modified'])}").classes('text-caption text-grey-4')
                                                ui.icon('analytics').classes('text-primary').style('font-size: 14px;')

                            refresh_outputs()

        # CENTER Panel: Pipeline Execution
        with ui.column().classes('col').style('height: 100%;'):
            with ui.card().classes('q-pa-lg bg-white w-full').style(
                'border: 1px solid #e2e8f0; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.04); height: 100%; display: flex; flex-direction: column; overflow: hidden; min-height: 0;'
            ):
                # State variables
                state = {
                    'execution_id': None,
                    'status': 'idle',
                    'progress': 0.0,
                    'current_step': 'Not started',
                    'log_lines': []
                }
                rendered_logs_count = 0

                def format_log_to_html(log_entry):
                    timestamp_raw = log_entry.get('timestamp', '')
                    step = log_entry.get('step', '')
                    message = log_entry.get('message', '')
                    is_raw = log_entry.get('is_raw', False)
                    
                    try:
                        if 'T' in timestamp_raw:
                            time_part = timestamp_raw.split('T')[1].split('.')[0]
                        else:
                            time_part = timestamp_raw
                    except Exception:
                        time_part = timestamp_raw
                        
                    msg_color = '#e2e8f0' # Slate-200
                    msg_lower = message.lower()
                    if 'fail' in msg_lower or 'error' in msg_lower or 'reject' in msg_lower:
                        msg_color = '#f87171' # Red-400
                    elif 'success' in msg_lower or 'complete' in msg_lower or 'finished' in msg_lower:
                        msg_color = '#4ade80' # Green-400
                    elif 'warning' in msg_lower:
                        msg_color = '#fbbf24' # Amber-400
                        
                    escaped_message = message.replace('<', '&lt;').replace('>', '&gt;')
                    if is_raw:
                        return f'<span style="color: {msg_color};">{escaped_message}</span>'
                    else:
                        return f'<span style="color: #64748b;">[{time_part}]</span> <span style="color: #60a5fa; font-weight: bold;">[{step}]</span> <span style="color: {msg_color};">{escaped_message}</span>'

                # Polling Callback & Logic
                def poll_status():
                    nonlocal rendered_logs_count
                    exec_id = state['execution_id']
                    if not exec_id:
                        polling_timer.deactivate()
                        return
                    
                    try:
                        # Fetch and update status
                        status_data = get_execution_status(exec_id)
                        status = status_data.get('status', 'failed')
                        progress = status_data.get('progress', 0)
                        current_step = status_data.get('current_step', 'Unknown')
                        
                        state['status'] = status
                        state['progress'] = progress
                        state['current_step'] = current_step
                        
                        # Update status dashboard header
                        step_label.set_text(current_step)
                        progress_bar.set_value(progress / 100.0)
                        progress_label.set_text(f"{int(progress)}%")
                        
                        if status == 'running':
                            status_badge.set_text('RUNNING')
                            status_badge.style('background-color: #2563eb;')
                        elif status == 'completed':
                            status_badge.set_text('COMPLETED')
                            status_badge.style('background-color: #16a34a;')
                        elif status == 'failed':
                            status_badge.set_text('FAILED')
                            status_badge.style('background-color: #dc2626;')
                        
                        # Fetch and append logs in real-time (no duplicates)
                        logs = get_execution_logs(exec_id)
                        if len(logs) > rendered_logs_count:
                            new_lines = []
                            for i in range(rendered_logs_count, len(logs)):
                                new_lines.append(format_log_to_html(logs[i]))
                            state['log_lines'].extend(new_lines)
                            
                            # Update HTML content
                            log_console.set_content('<br>'.join(state['log_lines']))
                            rendered_logs_count = len(logs)
                            
                            # Auto-scroll to bottom of the console
                            ui.run_javascript(f'const el = document.getElementById("c{log_console.id}"); if (el) el.scrollTop = el.scrollHeight;')
                        
                        # Stop polling if execution hits terminal state
                        if status in ('completed', 'failed'):
                            polling_timer.deactivate()
                            start_button.visible = True
                            if status == 'completed':
                                ui.notify('Pipeline completed successfully!', type='positive')
                            else:
                                ui.notify(f"Pipeline failed: {status_data.get('error_message', 'Unknown error')}", type='negative')
                            refresh_outputs() # Refresh Output Files list
                            
                    except Exception as ex:
                        print(f"Error polling pipeline execution: {ex}")

                polling_timer = ui.timer(1.0, poll_status, active=False)

                def on_start_click():
                    nonlocal rendered_logs_count
                    try:
                        # Hide start button
                        start_button.visible = False
                        
                        # Trigger pipeline
                        exec_id = start_pipeline(user_id)
                        
                        # Reset states
                        state['execution_id'] = exec_id
                        state['status'] = 'running'
                        state['progress'] = 0.0
                        state['current_step'] = 'Initializing...'
                        state['log_lines'] = [
                            '<span style="color: #64748b;">[System] Spawning pipeline thread...</span>',
                            f'<span style="color: #64748b;">[System] Execution ID: {exec_id}</span>'
                        ]
                        rendered_logs_count = 0
                        
                        # Update UI elements
                        step_label.set_text('Initializing...')
                        status_badge.set_text('RUNNING')
                        status_badge.style('background-color: #2563eb;')
                        progress_bar.set_value(0.0)
                        progress_label.set_text('0%')
                        
                        # Clear console and set initial lines
                        log_console.set_content('<br>'.join(state['log_lines']))
                        
                        ui.notify('Pipeline started successfully!', type='info')
                        
                        # Start polling status
                        polling_timer.activate()
                        
                    except Exception as ex:
                        start_button.visible = True
                        ui.notify(f"Failed to start pipeline: {str(ex)}", type='negative')

                # ── Title and Run Button Top Row ──────────────────────────────────
                with ui.row().classes('w-full items-center justify-between no-wrap q-mb-md'):
                    ui.label('Pipeline Execution') \
                      .classes('text-h6 text-weight-bold q-my-none') \
                      .style('color: #0f172a;')
                    
                    start_button = ui.button('START PIPELINE', on_click=on_start_click) \
                        .props('no-caps icon=play_arrow') \
                        .classes('text-white') \
                        .style('background: #2563eb; border-radius: 8px; font-weight: 600; padding: 4px 16px;')

                # ── 1. EXECUTION STATUS DASHBOARD (TOP SECTION) ───────────────────
                with ui.row().classes('w-full items-center justify-between no-wrap q-mb-xs'):
                    step_label = ui.label('Idle').classes('text-lg font-bold text-slate-800 truncate')
                    status_badge = ui.label('IDLE').classes('q-px-sm q-py-xs text-white text-xs font-bold rounded bg-slate-400')

                with ui.row().classes('w-full items-center gap-4 no-wrap q-mb-md'):
                    progress_bar = ui.linear_progress(value=0.0, show_value=False).classes('col-grow')
                    progress_label = ui.label('0%').classes('text-xs font-bold text-slate-600')

                # ── 2. TERMINAL-LIKE LOG CONSOLE (MAIN AREA) ──────────────────────
                log_console = ui.html(
                    '<span style="color: #64748b;">[OnboardIQ Console v1.0] Ready. Click START PIPELINE to begin.</span>'
                ).classes('w-full col-grow terminal-scroll p-4').style(
                    'flex: 1 1 0%; min-height: 250px; overflow-y: scroll; '
                    'background-color: #0f172a; font-family: "Fira Code", Courier, monospace; font-size: 11px; '
                    'white-space: pre-wrap; border-radius: 12px; border: 1px solid #1e293b;'
                )

        # RIGHT Panel: Chat Assistant
        with ui.column().classes('col-3').style('min-width: 280px; height: 100%;'):
            with ui.card().classes('q-pa-lg bg-white w-full').style(
                'border: 1px solid #e2e8f0; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.04); height: 100%; overflow: hidden;'
            ):
                ui.label('Chat Assistant') \
                  .classes('text-h6 text-weight-bold q-mb-md') \
                  .style('color: #0f172a;')
                ui.label('The persistent AI assistant and pipeline command logs will appear here.') \
                  .classes('text-body2') \
                  .style('color: #64748b;')
