"""
frontend/logo.py
----------------
Smile-face SVG Logo definitions for OnboardIQ UI.
Exactly matches the logo from the reference image:
- An open "C" shape outer blue ring.
- A solid blue center circle.
- A bottom dot (blue for left-panel primary logo, purple for right-panel login avatar).
"""

def logo_svg(size: int = 40, is_avatar: bool = False) -> str:
    """Build the OnboardIQ logo SVG at the requested pixel size.
    
    If is_avatar is True, it draws the avatar version with a purple dot at the bottom-right.
    If is_avatar is False, it draws the primary version with a blue dot at the bottom-left.
    """
    dot_color = "#8b5cf6" if is_avatar else "#2563eb"
    dot_cx = "75" if is_avatar else "25"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="{size}" height="{size}">'
        # Outer C shape: circle arc from 225 deg (bottom-left) through top to 315 deg (bottom-right)
        '<path d="M 25 75 A 36 36 0 1 1 75 75" fill="none" stroke="#2563eb" stroke-width="11" stroke-linecap="round"/>'
        # Center solid circle
        '<circle cx="50" cy="50" r="14" fill="#2563eb"/>'
        # Bottom overlapping dot (blue for primary, purple for avatar)
        f'<circle cx="{dot_cx}" cy="75" r="11" fill="{dot_color}"/>'
        '</svg>'
    )

# Pre-built logo strings for safe embedding in templates
LOGO_38 = logo_svg(38, is_avatar=False)
LOGO_46 = logo_svg(46, is_avatar=True)
LOGO_32 = logo_svg(32, is_avatar=False)
