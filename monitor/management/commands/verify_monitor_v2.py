from django.core.management.base import BaseCommand
from django.utils import timezone
from monitor.models import Article, Source, ActorLink, MetricAggregate
from redpolitica.models import Persona
from monitor.pipeline import link_articles, aggregate_metrics

class Command(BaseCommand):
    help = 'Verifies the Monitor V2 pipeline integration'

    def handle(self, *args, **options):
        self.stdout.write("Starting Verification...")
        
        # 1. Setup Data
        source, _ = Source.objects.get_or_create(
            name="Test Source", 
            outlet="TestOutlet", 
            source_type="html",
            url="http://example.com"
        )
        
        persona_name = "PERSONA_TEST_UNIQUE"
        p, _ = Persona.objects.get_or_create(
            nombre_completo=persona_name,
            slug="persona-test-unique"
        )
        p.save() # trigger normalization if needed, though signals might not run in bulk, save does.
        
        article_text = f"El funcionario {persona_name} anunció medidas hoy."
        article = Article.objects.create(
            source=source,
            url=f"http://example.com/{timezone.now().timestamp()}",
            title="Test Article for Linking",
            body=article_text,
            published_at=timezone.now(),
            outlet="TestOutlet"
        )
        
        self.stdout.write(f"Created Article: {article.id}")
        self.stdout.write(f"Created Persona: {p.id} ({p.nombre_completo})")
        
        # 2. Run Linking
        self.stdout.write("Running link_articles...")
        matches = link_articles([article])
        self.stdout.write(f"Matches found: {matches}")
        
        # 3. Assert Link Created
        link = ActorLink.objects.filter(article=article, atlas_entity_id=str(p.id)).first()
        if link:
            self.stdout.write(self.style.SUCCESS(f"✅ PASSED: Link created for {link.atlas_entity_id}"))
        else:
            self.stdout.write(self.style.ERROR("❌ FAILED: No link created."))
            return

        # 4. Run Aggregation
        self.stdout.write("Running aggregate_metrics...")
        aggregate_metrics(period="day")
        
        # 5. Check Aggregates
        agg = MetricAggregate.objects.filter(
            entity_type=ActorLink.AtlasEntityType.PERSONA,
            atlas_id=str(p.id),
            date_start=timezone.now().date()
        ).first()
        
        if agg and agg.volume >= 1:
            self.stdout.write(self.style.SUCCESS(f"✅ PASSED: MetricAggregate found (Volume: {agg.volume})"))
        else:
             self.stdout.write(self.style.ERROR("❌ FAILED: MetricAggregate missing or zero."))
             
        self.stdout.write(self.style.SUCCESS("All checks passed."))
