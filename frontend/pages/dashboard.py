"""
frontend/pages/dashboard.py
---------------------------
Dashboard view showing onboarding state and details.
"""

from nicegui import app, ui
from frontend.logo import LOGO_32

@ui.page('/')
def dashboard_page():
    username = app.storage.user.get('username', 'Guest')

    ui.add_head_html('''
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
      body { font-family: 'Inter', sans-serif !important; background-color: #f8fafc !important; color: #1e293b; }
    </style>
    ''')

    def handle_logout():
        app.storage.user.clear()
        ui.navigate.to('/login')

    # Main Header Bar
    with ui.row().classes('w-full items-center justify-between q-pa-md bg-white').style('border-bottom: 1px solid #e2e8f0; position: sticky; top: 0; z-index: 10;'):
        with ui.row().classes('items-center gap-2'):
            ui.html(LOGO_32)
            ui.html('<span style="font-size:1.1rem; font-weight:700; color:#0f172a; letter-spacing:-0.3px;">Onboard<span style="color:#2563eb;">IQ</span></span>')
            ui.html('<span style="font-size:0.7rem; font-weight:600; color:#2563eb; background:#eff6ff; border:1px solid #bfdbfe; border-radius:20px; padding:2px 8px;">v1.0</span>')

        with ui.row().classes('items-center q-gutter-md'):
            ui.label(f'Logged in as: {username}').classes('text-body2 text-weight-medium').style('color: #334155;')
            ui.button('Logout', on_click=handle_logout).props('flat dense icon=logout').style('color: #ef4444; font-weight: 600;')

    # Main Container splitting the layout
    with ui.row().classes('w-full no-wrap q-pa-xl gap-6') as main_container:
        # Left Panel (placeholder)
        left_panel = ui.column().classes('hidden')
        
        # Center Panel containing current dashboard welcome workspace card
        with ui.column().classes('col-grow') as center_panel:
            with ui.card().classes('q-pa-xl bg-white w-full').style('border: 1px solid #e2e8f0; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.04);'):
                ui.label(f'Welcome back, {username}!').classes('text-h4 text-weight-bold q-mb-xs').style('color: #0f172a;')
                ui.label('Your secure isolated workspace is ready.').classes('text-subtitle1 q-mb-lg').style('color: #64748b;')

                with ui.column().classes('w-full q-pa-md q-my-md').style('border-radius: 12px; border: 1px solid #bfdbfe; background: #eff6ff;'):
                    ui.label('User Space Isolation').classes('text-weight-bold text-caption q-mb-xs').style('color: #2563eb;')
                    ui.label(f'Output path: outputs/users/{username}/').classes('text-weight-medium text-body2').style('color: #1e40af;')
                    ui.label('All reports, catalogs, and mappings are stored exclusively in your folder.').classes('text-caption').style('color: #3b82f6;')

                ui.button('Proceed to Pipeline', on_click=lambda: ui.notify('Pipeline interface loading...')).props('no-caps').classes('q-mt-md q-px-lg q-py-sm text-white').style('background: #2563eb; border-radius: 8px; font-weight: 600;')

        # Right Panel (placeholder)
        right_panel = ui.column().classes('hidden')
