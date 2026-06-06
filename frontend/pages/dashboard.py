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
from backend.pipeline_service import get_user_source_files
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
                'border: 1px solid #e2e8f0; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.04); height: 100%; overflow: hidden;'
            ):
                ui.label('Pipeline Execution') \
                  .classes('text-h6 text-weight-bold q-mb-md') \
                  .style('color: #0f172a;')
                
                ui.label(f'Welcome back, {username}!') \
                  .classes('text-subtitle1 text-weight-bold q-mb-xs') \
                  .style('color: #0f172a;')
                
                with ui.column().classes('w-full q-pa-md q-my-md').style(
                    'border-radius: 12px; border: 1px solid #bfdbfe; background: #eff6ff;'
                ):
                    ui.label('User Space Isolation') \
                      .classes('text-weight-bold text-caption q-mb-xs') \
                      .style('color: #2563eb;')
                    ui.label(f'Output path: outputs/users/{username}/') \
                      .classes('text-weight-medium text-body2') \
                      .style('color: #1e40af;')
                    ui.label('All reports, catalogs, and mappings are stored exclusively in your folder.') \
                      .classes('text-caption') \
                      .style('color: #3b82f6;')

                ui.button('Proceed to Pipeline', on_click=lambda: ui.notify('Pipeline interface loading...')) \
                  .props('no-caps') \
                  .classes('q-mt-md q-px-lg q-py-sm text-white') \
                  .style('background: #2563eb; border-radius: 8px; font-weight: 600;')

        # RIGHT Panel: Chat Assistant
        with ui.column().classes('col').style('height: 100%;'):
            with ui.card().classes('q-pa-lg bg-white w-full').style(
                'border: 1px solid #e2e8f0; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.04); height: 100%; overflow: hidden;'
            ):
                ui.label('Chat Assistant') \
                  .classes('text-h6 text-weight-bold q-mb-md') \
                  .style('color: #0f172a;')
                ui.label('The persistent AI assistant and pipeline command logs will appear here.') \
                  .classes('text-body2') \
                  .style('color: #64748b;')
