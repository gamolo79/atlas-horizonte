try:
    from monitor.views_dashboard import article_list
    from monitor.models import Article
    from django.test import RequestFactory
    
    print("Checking Article.PipelineStatus...")
    print(Article.PipelineStatus.choices)
    
    print("Running View...")
    factory = RequestFactory()
    request = factory.get("/monitor/dashboard/articles/")
    request.user = type("User", (), {"is_authenticated": True, "is_staff": True, "is_active": True})()
    
    response = article_list(request)
    print("View Executed Status:", response.status_code)
    
    # Render if possible (this triggers template errors)
    if hasattr(response, 'render'):
        response.render()
        print("Render Success")
    print("Response Content Length:", len(response.content))

except Exception as e:
    print("CRASHED:")
    import traceback
    traceback.print_exc()
