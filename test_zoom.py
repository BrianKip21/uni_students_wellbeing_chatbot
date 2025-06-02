import os
from datetime import datetime, timedelta
from wellbeing.utils.zoom_integration import test_zoom_integration

# Test the integration
if test_zoom_integration():
    print("✅ Zoom integration working!")
    print("🎉 Real Zoom meetings will be created!")
else:
    print("❌ Zoom integration failed")
    print("📋 Check your API credentials")