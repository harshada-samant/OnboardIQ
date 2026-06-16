"""
frontend/pages/dashboard.py
---------------------------
Dashboard view showing onboarding state and details.
Pure NiceGUI — no raw HTML inputs or JavaScript.
"""

from datetime import datetime
from pathlib import Path
import pandas as pd
from nicegui import app, ui, Client
from frontend.logo import LOGO_32

# Backend service integrations
from backend.pipeline_service import (
    get_user_source_files,
    start_pipeline,
    get_execution_status,
    get_execution_logs,
    get_chat_history,
    send_chat_message,
    start_pipeline_step,
    get_pipeline_progress,
    reset_pipeline
)
from backend.schema_service import get_schema_options, get_user_schema_selection, update_user_schema_selection
from backend.database import get_username_by_id
from backend.adapters.storage_interface import LocalStorageBackend, S3StorageBackend
from backend.adapters.s3_source_adapter import S3SourceAdapter
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
async def dashboard_page(client: Client):
    # Enforce sessionStorage check to detect tab/window closes vs page refreshes
    await client.connected()
    is_active = await ui.run_javascript("sessionStorage.getItem('session_active')")
    if is_active != 'true':
        app.storage.user.clear()
        ui.navigate.to('/login')
        return

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
      .terminal-scroll {
        overflow-y: auto !important;
        flex-grow: 1 !important;
        min-height: 200px;
      }
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
        ui.run_javascript("sessionStorage.removeItem('session_active');")
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

                            async def handle_schema_upload(e):
                                filename = e.file.name
                                if not filename.endswith('.json'):
                                    ui.notify('Only JSON target schemas are supported', type='warning')
                                    return
                                try:
                                    username = get_username_by_id(user_id)
                                    schema_path = config.WORKSPACES_DIR / "users" / username / "schemas" / filename
                                    await e.file.save(str(schema_path))
                                    
                                    # Refresh dropdown options
                                    new_options = get_schema_options()
                                    schema_dropdown.options = new_options
                                    schema_dropdown.value = filename
                                    
                                    # Select and save selection
                                    update_user_schema_selection(user_id, filename)
                                    ui.notify(f'Schema {filename} uploaded and selected', type='positive')
                                except Exception as ex:
                                    ui.notify(f'Failed to upload schema: {ex}', type='negative')

                            ui.upload(on_upload=handle_schema_upload, auto_upload=True) \
                                .classes('w-full q-mt-xs') \
                                .props('accept=.json label="Upload Target Schema (.json)" flat bordered dense color=primary')

                        ui.separator().classes('q-my-sm')

                        def show_preview(filename: str, directory_type: str = "uploads"):
                            username = get_username_by_id(user_id)
                            
                            file_buf = None
                            if config.USE_S3_SOURCE and directory_type == "uploads":
                                try:
                                    prefix = config.s3_input_prefix(username)
                                    adapter = S3SourceAdapter(config.S3_BUCKET, prefix)
                                    s3_files = adapter.list_source_files()
                                    key = next((f["key"] for f in s3_files if f["name"].lower() == filename.lower()), None)
                                    if not key:
                                        ui.notify(f"File not found on S3: {filename}", type='warning')
                                        return
                                    file_buf = adapter.stream_file(key)
                                    if file_buf is None:
                                        ui.notify(f"Failed to read file from S3: {filename}", type='negative')
                                        return
                                except Exception as s3_err:
                                    ui.notify(f"S3 access error: {s3_err}", type='negative')
                                    return
                            else:
                                file_path = config.WORKSPACES_DIR / "users" / username / directory_type / filename
                                if not file_path.exists():
                                    ui.notify(f"File not found: {filename}", type='warning')
                                    return
                                    
                            columns = []
                            rows = []
                            is_table = False
                            text_content = ""
                            
                            try:
                                if filename.lower().endswith('.csv'):
                                    import pandas as pd
                                    if file_buf is not None:
                                        df = pd.read_csv(file_buf, nrows=10)
                                    else:
                                        df = pd.read_csv(file_path, nrows=10)
                                    df = df.fillna('')
                                    is_table = True
                                    columns = [{'name': col, 'label': col, 'field': col, 'align': 'left'} for col in df.columns]
                                    rows = df.to_dict(orient='records')
                                elif filename.lower().endswith('.json'):
                                    import json
                                    try:
                                        if file_buf is not None:
                                            file_buf.seek(0)
                                            parsed = json.loads(file_buf.read().decode('utf-8', errors='replace'))
                                        else:
                                            with open(file_path, 'r', encoding='utf-8') as f:
                                                parsed = json.load(f)
                                        # Pretty print JSON
                                        text_content = json.dumps(parsed, indent=2)
                                    except Exception:
                                        if file_buf is not None:
                                            file_buf.seek(0)
                                            text_content = file_buf.read().decode('utf-8', errors='replace')[:2000]
                                        else:
                                            with open(file_path, 'r', encoding='utf-8') as f:
                                                text_content = f.read(2000)
                                else:
                                    if file_buf is not None:
                                        file_buf.seek(0)
                                        text_content = file_buf.read().decode('utf-8', errors='replace')
                                    else:
                                        with open(file_path, 'r', encoding='utf-8') as f:
                                            text_content = f.read()
                            except Exception as ex:
                                ui.notify(f"Error reading preview: {ex}", type='negative')
                                return

                            with ui.dialog() as dialog, ui.card().style('width: 900px; max-width: 95vw; max-height: 80vh; border-radius: 16px; display: flex; flex-direction: column; overflow: hidden;'):
                                with ui.row().classes('w-full items-center justify-between no-wrap q-pa-md bg-slate-50').style('border-bottom: 1px solid #e2e8f0;'):
                                    with ui.row().classes('items-center gap-2 no-wrap'):
                                        ui.label(f"File Preview: {filename}").classes('text-weight-bold text-slate-800').style('font-size: 1.1rem;')
                                        ui.label(f"Type: {directory_type.capitalize()}").classes('text-caption text-slate-500 bg-slate-100 rounded q-px-sm q-py-xs')
                                    ui.button(icon='close', on_click=dialog.close).props('flat round dense').classes('text-slate-500')
                                    
                                with ui.column().classes('w-full q-pa-md col-grow custom-scroll').style('overflow-y: auto; max-height: 55vh; min-height: 0;'):
                                    if is_table:
                                        if not rows:
                                            ui.label("This file is empty.").classes('text-slate-500 text-center q-my-md')
                                        else:
                                            ui.table(columns=columns, rows=rows).classes('w-full').props('dense flat bordered wrap-cells')
                                    else:
                                        if not text_content:
                                            ui.label("This file is empty.").classes('text-slate-500 text-center q-my-md')
                                        else:
                                            if filename.lower().endswith('.md'):
                                                ui.markdown(text_content).classes('w-full text-xs text-slate-700')
                                            else:
                                                ui.code(text_content).classes('w-full').style('font-family: monospace; font-size: 11px;')
                                
                                with ui.row().classes('w-full justify-end q-pa-md bg-slate-50').style('border-top: 1px solid #e2e8f0;'):
                                    ui.button('Close', on_click=dialog.close).props('unelevated').style('background: #64748b; color: white; border-radius: 8px; font-weight: 600;')
                            
                            dialog.open()

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
                                            with ui.row().classes('w-full items-center justify-between no-wrap p-1 border-b border-slate-50 hover:bg-slate-50 rounded') \
                                                    .style('cursor: pointer;') \
                                                    .on('click', lambda *_, name=f['name']: show_preview(name)):
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
                                            with ui.row().classes('w-full items-center justify-between no-wrap p-1 border-b border-slate-50 hover:bg-slate-50 rounded') \
                                                    .style('cursor: pointer;') \
                                                    .on('click', lambda *_, name=f['name']: show_preview(name, "outputs")):
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

                STEPS = [
                    ("Discovery", "entity_catalog.json", "Discovery Agent"),
                    ("Profiling", "quality_report.json", "Profiling Agent"),
                    ("Mapping", "mapping_document.json", "Mapping Agent"),
                    ("Specification", "migration_spec.json", "Specification Agent"),
                    ("Readiness", "readiness_report.json", "Readiness Agent"),
                    ("Planning", "onboarding_plan.json", "Planning Agent"),
                    ("Migration Agent", "migration_validation.json", "Migration Agent")
                ]


                def get_current_pipeline_state():
                    try:
                        progress_info = get_pipeline_progress(user_id)
                        return progress_info["completed_steps"], progress_info["next_step"]
                    except Exception as e:
                        print(f"Error fetching progress: {e}")
                        return [], "Discovery"

                def load_output_json(filename: str) -> dict:
                    import json
                    path = config.WORKSPACES_DIR / "users" / username / "outputs" / filename
                    if path.is_file():
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                return json.load(f)
                        except Exception as e:
                            print(f"Error loading {filename}: {e}")
                    return None

                def load_output_text(filename: str) -> str:
                    path = config.WORKSPACES_DIR / "users" / username / "outputs" / filename
                    if path.is_file():
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                return f.read()
                        except Exception as e:
                            print(f"Error loading {filename}: {e}")
                    return ""

                def format_log_to_html(log_entry):
                    timestamp_raw = log_entry.get('timestamp', '')
                    step = log_entry.get('step', '')
                    message = log_entry.get('message', '')
                    is_raw = log_entry.get('is_raw', False)

                    # 1. Clean up separators and empty lines
                    stripped = message.strip()
                    if not stripped or all(c in '=-_*~' for c in stripped):
                        return None
                        
                    # 2. Filter out developer details / raw logs that are noisy
                    noise_keywords = [
                        'saved to:', 'saved md to:', 'saved json to:', 'checkpoint', 
                        'exported execution json', 'max retries',
                        'audit report', 'to rerun from scratch', 'attempt',
                        'rate limit', 'groq call also failed', 'failed after retries',
                        'invalid json output on parse attempt', 'sub-score will degrade',
                        'circular fk dependencies detected', 'loaded from disk',
                        'failed tables:', 'unexpected error on', 'no files could be read',
                        'file registry:', 'logical table(s)', 'sources:', 'logical table:',
                        'succeeded,', 'failed tables', 'failed tables :', 'checkpoint status',
                        'spawning pipeline thread', 'spawning', 'execution id:',
                        'per-table checkpoints saved', 'to rerun from scratch'
                    ]
                    msg_lower = message.lower()
                    if any(kw in msg_lower for kw in noise_keywords):
                        return None
                        
                    # Also skip paths / system internals
                    if '/workspaces/' in msg_lower or '\\workspaces\\' in msg_lower:
                        return None
                    if '[system] spawning' in msg_lower or '[system] execution id:' in msg_lower:
                        return None

                    # 3. Clean up and map friendly headers / agent names
                    header_translations = {
                        "DISCOVERY AGENT": "🔍 Discovery Agent Initialized",
                        "DISCOVERY AGENT COMPLETE": "✅ Discovery Agent Run Complete",
                        "DATA PROFILING AGENT": "📊 Data Profiling Agent Initialized",
                        "DATA PROFILING COMPLETE": "✅ Data Profiling Agent Run Complete",
                        "AI MAPPING AGENT": "🗺️ AI Mapping Agent Initialized",
                        "AI MAPPING COMPLETE": "✅ AI Mapping Agent Run Complete",
                        "AI SPECIFICATION AGENT": "📝 AI Specification Agent Initialized",
                        "SPECIFICATION GENERATION COMPLETE": "✅ Specification Generation Complete",
                        "MIGRATION READINESS AGENT": "🛡️ Migration Readiness Agent Initialized",
                        "MIGRATION READINESS COMPLETE": "✅ Migration Readiness Assessment Complete",
                        "ONBOARDING PLANNING AGENT": "📅 Onboarding Planning Agent Initialized",
                        "ONBOARDING PLANNING COMPLETE": "✅ Onboarding Plan Design Complete"
                    }
                    
                    matched_translation = None
                    for key, val in header_translations.items():
                        if key in stripped:
                            matched_translation = val
                            break
                            
                    if matched_translation:
                        message = matched_translation
                    else:
                        # Clean up prefixing whitespaces/indents for list display
                        # Let's keep 2 spaces if they are nested, but remove long indents
                        if message.startswith('    - '):
                            message = '  • ' + message[6:]
                        elif message.startswith('    ~ '):
                            message = '  • ' + message[6:]
                        elif message.startswith('    ! '):
                            message = '  ⚠️ ' + message[6:]
                        elif message.startswith('  + '):
                            message = '✨ ' + message[4:]
                        elif message.startswith('  ~ '):
                            message = 'ℹ️ ' + message[4:]
                        elif message.startswith('  x '):
                            message = '❌ ' + message[4:]
                        elif message.startswith('  * '):
                            message = '🔹 ' + message[4:]
                        elif message.startswith('  ! '):
                            message = '⚠️ ' + message[4:]
                        elif message.startswith('+ '):
                            message = '✨ ' + message[2:]
                        elif message.startswith('* '):
                            message = '🔹 ' + message[2:]
                        elif message.startswith('! '):
                            message = '⚠️ ' + message[2:]
                        elif message.startswith('x '):
                            message = '❌ ' + message[2:]
                            
                    # 4. Map system status logs
                    if not is_raw:
                        if "execution started for step:" in msg_lower:
                            step_name = message.split(":")[-1].strip()
                            message = f"🚀 Starting {step_name} Agent execution..."
                        elif "execution completed with status: completed" in msg_lower:
                            message = "✨ Step completed successfully."
                        elif "execution completed with status: failed" in msg_lower:
                            message = "❌ Step execution failed."
                            
                    try:
                        if 'T' in timestamp_raw:
                            time_part = timestamp_raw.split('T')[1].split('.')[0]
                        else:
                            time_part = timestamp_raw
                    except Exception:
                        time_part = timestamp_raw
                        
                    msg_color = '#e2e8f0' # Slate-200
                    msg_lower = message.lower()
                    if 'fail' in msg_lower or 'error' in msg_lower or 'reject' in msg_lower or '❌' in message:
                        msg_color = '#f87171' # Red-400
                    elif 'success' in msg_lower or 'complete' in msg_lower or 'finished' in msg_lower or '✨' in message or '✅' in message:
                        msg_color = '#4ade80' # Green-400
                    elif 'warning' in msg_lower or '⚠️' in message:
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
                                formatted = format_log_to_html(logs[i])
                                if formatted:
                                    new_lines.append(formatted)
                            state['log_lines'].extend(new_lines)
                            
                            # Update HTML content
                            log_console.set_content('<br>'.join(state['log_lines']))
                            rendered_logs_count = len(logs)
                            
                            # Auto-scroll to bottom of the console
                            ui.run_javascript(f'const el = document.getElementById("c{log_console.id}"); if (el) el.scrollTop = el.scrollHeight;')
                        
                        # Stop polling if execution hits terminal state
                        if status in ('completed', 'failed'):
                            polling_timer.deactivate()
                            display_step = "Migration Agent" if current_step == "MigrationAgent" else current_step
                            if status == 'completed':
                                ui.notify('Completed successfully!', type='positive')
                                refresh_stepper_ui()
                                refresh_action_button()
                                refresh_outputs()
                            else:
                                ui.notify(f"{display_step} failed: {status_data.get('error_message', 'Unknown error')}", type='negative')
                            refresh_outputs() # Refresh Output Files list
                            
                    except Exception as ex:
                        print(f"Error polling pipeline execution: {ex}")

                polling_timer = ui.timer(1.0, poll_status, active=False)

                def refresh_stepper_ui():
                    stepper_container.clear()
                    completed, next_step = get_current_pipeline_state()
                    
                    with stepper_container:
                        for idx, (step_name, filename, display_label) in enumerate(STEPS):
                            is_completed = step_name in completed
                            is_running = state['status'] == 'running' and state['current_step'] == step_name
                            is_next = step_name == next_step and state['status'] != 'running'
                            
                            if is_completed:
                                bg = '#f0fdf4'  # green-50
                                border = '1px solid #bbf7d0'  # green-200
                                text_color = '#15803d'  # green-700
                                icon_name = 'check_circle'
                            elif is_running:
                                bg = '#eff6ff'  # blue-50
                                border = '1px solid #bfdbfe'  # blue-200
                                text_color = '#1d4ed8'  # blue-700
                                icon_name = 'autorenew'
                            elif is_next:
                                bg = '#fffbeb'  # amber-50
                                border = '1px dashed #fde047'  # amber-200
                                text_color = '#b45309'  # amber-700
                                icon_name = 'play_circle'
                            else:
                                bg = '#f8fafc'  # slate-50
                                border = '1px solid #cbd5e1'  # slate-300
                                text_color = '#94a3b8'  # slate-400
                                icon_name = 'lock'
                                
                            card_style = f"background: {bg}; border: {border}; color: {text_color}; border-radius: 8px; cursor: default; padding: 6px 10px; display: flex; align-items: center; gap: 4px;"
                            with ui.row().style(card_style).classes('col flex-center no-wrap'):
                                ui.icon(icon_name).style('font-size: 14px;')
                                ui.label(f"{idx+1}. {step_name}").classes('text-xs font-bold truncate')

                def refresh_action_button():
                    completed, next_step = get_current_pipeline_state()
                    
                    if state['status'] == 'running':
                        display_step = "Migration Agent" if state['current_step'] == "MigrationAgent" else state['current_step']
                        start_button.set_text(f"Running {display_step}...")
                        start_button.disable()
                        start_button.style('background: #94a3b8; border-radius: 8px; font-weight: 600; padding: 4px 16px;')
                        reset_button.disable()
                    else:
                        reset_button.enable()
                        if not next_step:
                            start_button.set_text("Pipeline Completed")
                            start_button.disable()
                            start_button.style('background: #16a34a; border-radius: 8px; font-weight: 600; padding: 4px 16px;')
                        else:
                            start_button.set_text(f"RUN {next_step.upper()}")
                            start_button.enable()
                            start_button.style('background: #2563eb; border-radius: 8px; font-weight: 600; padding: 4px 16px;')

                def on_start_click():
                    nonlocal rendered_logs_count
                    try:
                        completed, next_step = get_current_pipeline_state()
                        if not next_step:
                            ui.notify('Pipeline is already fully completed!', type='warning')
                            return
                        
                        exec_id = start_pipeline_step(user_id, next_step)
                        
                        # Reset states
                        state['execution_id'] = exec_id
                        state['status'] = 'running'
                        state['progress'] = 0.0
                        state['current_step'] = next_step
                        state['log_lines'] = [
                            f'<span style="color: #60a5fa; font-weight: bold;">[System]</span> <span style="color: #e2e8f0;">🚀 Starting {next_step}...</span>'
                        ]
                        rendered_logs_count = 0
                        
                        # Update UI elements
                        step_label.set_text(next_step)
                        status_badge.set_text('RUNNING')
                        status_badge.style('background-color: #2563eb;')
                        progress_bar.set_value(0.0)
                        progress_label.set_text('0%')
                        
                        # Clear console and set initial lines
                        log_console.set_content('<br>'.join(state['log_lines']))
                        
                        ui.notify(f'{next_step} started successfully!', type='info')
                        
                        # Update button and stepper immediately
                        refresh_action_button()
                        refresh_stepper_ui()
                        
                        # Start polling status
                        polling_timer.activate()
                        
                    except Exception as ex:
                        refresh_action_button()
                        ui.notify(f"Failed to start step: {str(ex)}", type='negative')

                def on_reset_click():
                    try:
                        success = reset_pipeline(user_id)
                        if success:
                            ui.notify('Pipeline reset successfully. Start over from Step 1.', type='positive')
                            
                            # Clear log console
                            state['execution_id'] = None
                            state['status'] = 'idle'
                            state['progress'] = 0.0
                            state['current_step'] = 'Not started'
                            state['log_lines'] = []
                            
                            step_label.set_text('Idle')
                            status_badge.set_text('IDLE')
                            status_badge.style('background-color: #94a3b8;')
                            progress_bar.set_value(0.0)
                            progress_label.set_text('0%')
                            log_console.set_content('<span style="color: #64748b;">[OnboardIQ Console v1.0] Ready. Click RUN DISCOVERY AGENT to begin.</span>')
                            
                            # Refresh all UI elements
                            refresh_stepper_ui()
                            refresh_action_button()
                            refresh_outputs()
                        else:
                            ui.notify('Failed to reset pipeline.', type='negative')
                    except Exception as ex:
                        ui.notify(f"Reset failed: {ex}", type='negative')

                # ── Title and Run Button Top Row ──────────────────────────────────
                with ui.row().classes('w-full items-center justify-between no-wrap q-mb-sm'):
                    ui.label('Pipeline Execution') \
                      .classes('text-h6 text-weight-bold q-my-none') \
                      .style('color: #0f172a;')
                    
                    with ui.row().classes('items-center gap-2 no-wrap'):
                        reset_button = ui.button('RESET', on_click=on_reset_click) \
                            .props('flat dense icon=refresh') \
                            .classes('text-slate-500 hover:text-red-500') \
                            .style('font-weight: 600; border-radius: 6px;')
                            
                        start_button = ui.button('RUN DISCOVERY AGENT', on_click=on_start_click) \
                            .props('no-caps icon=play_arrow') \
                            .classes('text-white') \
                            .style('background: #2563eb; border-radius: 8px; font-weight: 600; padding: 4px 16px;')

                # ── Horizontal Stepper Wizard Timeline ────────────────────────────
                stepper_container = ui.row().classes('w-full items-center justify-between gap-1 q-mb-md q-pa-sm').style(
                    'background-color: #f8fafc; border-radius: 12px; border: 1px solid #e2e8f0; min-height: 44px;'
                )

                # ── 1. EXECUTION STATUS DASHBOARD (TOP SECTION) ───────────────────
                with ui.row().classes('w-full items-center justify-between no-wrap q-mb-xs'):
                    step_label = ui.label('Idle').classes('text-lg font-bold text-slate-800 truncate')
                    status_badge = ui.label('IDLE').classes('q-px-sm q-py-xs text-white text-xs font-bold rounded bg-slate-400')

                with ui.row().classes('w-full items-center gap-4 no-wrap q-mb-md'):
                    progress_bar = ui.linear_progress(value=0.0, show_value=False).classes('col-grow')
                    progress_label = ui.label('0%').classes('text-xs font-bold text-slate-600')

                # ── 2. TERMINAL-LIKE LOG CONSOLE (MAIN AREA) ──────────────────────
                log_console = ui.html(
                    '<span style="color: #64748b;">[OnboardIQ Console v1.0] Ready. Click RUN DISCOVERY AGENT to begin.</span>'
                ).classes('w-full terminal-scroll p-4').style(
                    'flex-grow: 1; overflow-y: auto; height: 0; min-height: 200px; '
                    'background-color: #0f172a; font-family: "Fira Code", Courier, monospace; font-size: 11px; '
                    'white-space: pre-wrap; border-radius: 12px; border: 1px solid #1e293b;'
                )

                # Trigger initial UI render state on page load
                refresh_stepper_ui()
                refresh_action_button()

        # RIGHT Panel: Chat Assistant
        with ui.column().classes('col-3').style('min-width: 280px; height: 100%;'):
            with ui.card().classes('q-pa-lg bg-white w-full').style(
                'border: 1px solid #e2e8f0; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.04); height: 100%; display: flex; flex-direction: column; overflow: hidden;'
            ):
                ui.label('Chat Assistant') \
                  .classes('text-h6 text-weight-bold q-my-none') \
                  .style('color: #0f172a;')
                ui.label('AI-driven onboarding guidance.') \
                  .classes('text-caption q-mb-sm') \
                  .style('color: #64748b;')
                
                ui.separator().classes('q-mb-md')

                # Scrollable message area
                chat_window = ui.column().classes('w-full col-grow custom-scroll p-1').style('overflow-y: auto; flex: 1 1 0%; min-height: 0;')

                def add_message(sender: str, text: str):
                    is_user = sender.lower() == 'user'
                    align_class = 'items-end' if is_user else 'items-start'
                    bg_style = (
                        'background: linear-gradient(135deg, #2563eb, #1d4ed8); color: white; '
                        'border-radius: 16px 16px 4px 16px;'
                        if is_user else
                        'background: #f1f5f9; color: #1e293b; '
                        'border-radius: 16px 16px 16px 4px; border: 1px solid #e2e8f0;'
                    )
                    avatar_url = 'https://cdn-icons-png.flaticon.com/512/149/149071.png' if is_user else 'https://cdn-icons-png.flaticon.com/512/4712/4712010.png'
                    
                    with chat_window:
                        with ui.column().classes(f'w-full {align_class} gap-1 q-mb-sm'):
                            with ui.row().classes('items-center gap-2 no-wrap'):
                                if not is_user:
                                    ui.image(avatar_url).style('width: 20px; height: 20px; border-radius: 50%;')
                                with ui.column().style(f'{bg_style} padding: 8px 12px; max-width: 85%; box-shadow: 0 1px 3px rgba(0,0,0,0.05);'):
                                    ui.label(text).classes('text-xs').style('white-space: pre-wrap; font-family: "Inter", sans-serif; line-height: 1.4;')
                                if is_user:
                                    ui.image(avatar_url).style('width: 20px; height: 20px; border-radius: 50%;')
                    
                    try:
                        ui.run_javascript(f'const el = document.getElementById("c{chat_window.id}"); if (el) el.scrollTop = el.scrollHeight;')
                    except Exception:
                        pass

                async def on_send():
                    text = chat_input.value
                    if not text or not text.strip():
                        return
                    
                    user_msg = text.strip()
                    add_message('User', user_msg)
                    chat_input.value = ''
                    
                    try:
                        from nicegui import run
                        # Invoke backend Bedrock chatbot asynchronously
                        result = await run.io_bound(send_chat_message, user_id, user_msg, state['execution_id'])
                        reply = result.get("response", "I could not process the message.")
                    except Exception as ex:
                        reply = f"Error communicating with assistant: {ex}"
                        
                    add_message('Assistant', reply)
                    refresh_outputs()
                    refresh_stepper_ui()
                    refresh_action_button()

                # Input bar and send button row at the bottom
                with ui.row().classes('w-full items-center gap-2 no-wrap q-mt-md').style('border-top: 1px solid #f1f5f9; padding-top: 12px;'):
                    chat_input = ui.input(placeholder='Type a message...').classes('col-grow').props('outlined dense')
                    chat_input.on('keydown.enter', on_send)
                    
                    ui.button(on_click=on_send, icon='send') \
                      .props('unelevated dense') \
                      .classes('text-white') \
                      .style('background: #2563eb; border-radius: 6px; width: 40px; height: 40px;')

                # Render persistent chat history on page load
                try:
                    chat_history = get_chat_history(user_id)
                except Exception:
                    chat_history = []

                if chat_history:
                    for msg in chat_history:
                        role = 'User' if msg['role'] == 'user' else 'Assistant'
                        add_message(role, msg['content'])
                else:
                    # Add initial greeting message
                    add_message('Assistant', "Welcome! I'm your data onboarding assistant. Ask me anything about your schema, file uploads, or pipeline waves.")
