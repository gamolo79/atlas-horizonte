import logging
import sys
from django.utils import timezone
from django.core.management import call_command
from monitor.models import IngestRun

LOGGER = logging.getLogger(__name__)

class MonitorPipeline:
    """
    Monitor 2.0 Central Pipeline Manager.
    Orchestrates: Ingest -> Classification (AI) -> Clustering -> Linking -> Synthesis.
    """

    def __init__(self, hours=24, limit=500, ai_model="gpt-4o-mini", dry_run=False):
        self.hours = hours
        self.limit = limit
        self.ai_model = ai_model
        self.dry_run = dry_run
        self.run_id = None

    def execute(self):
        """
        Main entry point.
        """
        print(f"--- Starting Monitor 2.0 Pipeline (Window: {self.hours}h) ---")
        self._start_run_tracking()

        try:
            # 1. Ingest (Placeholder logic calling existing commands or future scraper)
            # For now we assume fetch_sources is run separately or we call it if needed.
            # print("Step 1: Ingesting...")
            # call_command("fetch_sources", hours=self.hours)

            # 2. Intelligence Layer (Classification)
            print("Step 2: AI Classification (Topics)...")
            call_command("classify_article_topics", limit=self.limit, model=self.ai_model)
            
            # 3. Entity Extraction & Linking (NER)
            # First we link to generate mentions
            print("Step 3: Entity Linking...")
            call_command("link_entities", since=f"{self.hours}h", limit=self.limit, ai_model=self.ai_model, skip_ai_verify=False)

            # 4. Sentiment Analysis (Dependent on linked entities)
            print("Step 4: AI Sentiment Analysis...")
            # We classify sentiment for confirmed mentions
            call_command("classify_mentions_sentiment", limit=self.limit, model=self.ai_model, kind="both")

            # 5. Clustering
            print("Step 5: Leader-Based Clustering...")
            call_command("cluster_articles_ai", hours=self.hours, limit=self.limit, dry_run=self.dry_run)

            # 6. Synthesis (Digest) - Only if not dry run
            if not self.dry_run:
                print("Step 6: Generating Client Digests...")
                from monitor.models import DigestClient
                active_clients = DigestClient.objects.filter(is_active=True).select_related("config")
                
                if not active_clients.exists():
                    print("No active clients found. Skipping digest generation.")
                
                for client in active_clients:
                    try:
                        config = client.config
                        print(f"Generating digest for: {client.name}")
                        
                        cmd_args = [
                            "--title", config.title, 
                            "--top", str(config.top_n),
                            "--hours", str(config.hours or self.hours)
                        ]
                        
                        # Add Person IDs
                        p_ids = list(config.personas.values_list("id", flat=True))
                        for pid in p_ids:
                             cmd_args.extend(["--person-id", str(pid)])

                        # Add Institution IDs
                        i_ids = list(config.instituciones.values_list("id", flat=True))
                        for iid in i_ids:
                             cmd_args.extend(["--institution-id", str(iid)])
                        
                        # Add Topics (CSV)
                        if config.topics:
                            # topics is a list of strings
                            topics_str = ",".join(config.topics)
                            cmd_args.extend(["--topics", topics_str])

                        call_command("generate_client_digest", *cmd_args)
                        
                        # Apply AI Synthesis (Summaries)
                        call_command("create_digest_summary", "--model", self.ai_model)
                        
                    except Exception as exc:
                        print(f"Error generating digest for {client.name}: {exc}")
            
            self._finish_run_tracking("success")
            print("--- Pipeline Completed Successfully ---")

        except Exception as e:
            print(f"Pipeline Failed: {e}")
            self._finish_run_tracking("failed", log={"error": str(e)})
            raise e

    def _start_run_tracking(self):
        if self.dry_run: return
        start = timezone.now()
        end = start
        run = IngestRun.objects.create(
            trigger=IngestRun.Trigger.SCHEDULED,
            time_window_start=start - timezone.timedelta(hours=self.hours),
            time_window_end=end,
            status=IngestRun.Status.RUNNING,
            started_at=start,
        )
        self.run_id = run.id

    def _finish_run_tracking(self, status, log=None):
        if self.dry_run or not self.run_id: return
        run = IngestRun.objects.get(id=self.run_id)
        run.status = status
        run.finished_at = timezone.now()
        if log:
            run.log = log
        run.save()
