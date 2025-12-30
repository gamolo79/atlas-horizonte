import os
import django
from django.conf import settings
from django.test import RequestFactory
import sys

# Setup Django
sys.path.append("/Users/gabo/Documents/atlas-horizonte")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "atlas_core.settings")
django.setup()

from monitor.views_dashboard import article_list
from monitor.models import Article

print("Checking Article.PipelineStatus...")
try:
    print( Article.PipelineStatus.choices )
except Exception as e:
    print(f"FAILED accessing choices: {e}")

print("Running View...")
factory = RequestFactory()
request = factory.get("/monitor/dashboard/articles/")
request.user = type("User", (), {"is_authenticated": True, "is_staff": True, "is_active": True})()

try:
    response = article_list(request)
    print("View Executed Status:", response.status_code)
    
    # Try rendering content (if it's a TemplateResponse or HttpResponse)
    if hasattr(response, 'content'):
        print("Response Content Length:", len(response.content))
    
    print("SUCCESS")
except Exception as e:
    print("CRASHED:")
    import traceback
    traceback.print_exc()
