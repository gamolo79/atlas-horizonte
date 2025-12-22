import logging
import sys
import io
import traceback
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
        self.run_log = {}

    def log_step(self, step_name, status, output=""):
        print(f"[{step_name}] {status}")
        self.run_log[step_name] = {
            "status": status,
            "timestamp": str(timezone.now()),
            "output": output[:2000] # Truncate to avoid massive JSON
        }
        # Update DB incrementally so we can see progress/failure live
        if self.run_id:
            try:
                run = IngestRun.objects.get(id=self.run_id)
                run.log = self.run_log
                run.save(update_fields=["log"])
            except Exception:
                pass

    def run_command_captured(self, command_name, **kwargs):
        """
        Runs a management command and captures stdout/stderr for logging.
        """
        out = io.StringIO()
        err = io.StringIO()
        try:
            call_command(command_name, stdout=out, stderr=err, **kwargs)
            return True, out.getvalue()
        except Exception as e:
            return False, err.getvalue() + "\n" + str(e) + "\n" + traceback.format_exc()

    def execute(self):
        """
        Main entry point.
        """
        print(f"--- Starting Monitor 2.0 Pipeline (Window: {self.hours}h) ---")
        self._start_run_tracking()

        try:
            # 1. Ingest RSS
            success, output = self.run_command_captured("fetch_sources", limit=50)
            self.log_step("Step 1: Fetch RSS", "SUCCESS" if success else "FAILED", output)
            if not success:
                raise Exception(f"Fetch Sources Failed: {output}")

            # 2. Fetch Bodies
            success, output = self.run_command_captured("fetch_article_bodies", limit=self.limit)
            self.log_step("Step 2: Fetch Bodies", "SUCCESS" if success else "FAILED", output)
            
            # 3. Intelligence Layer (Classification - Topics)
            success, output = self.run_command_captured("classify_article_topics", limit=self.limit, model=self.ai_model)
            self.log_step("Step 3.1: AI Topics", "SUCCESS" if success else "FAILED", output)
            
            # 3.2 Entity Linking (Prior to Clustering)
            success, output = self.run_command_captured("link_entities", since=f"{self.hours}h", limit=self.limit, ai_model=self.ai_model, skip_ai_verify=False)
            self.log_step("Step 3.2: Linking", "SUCCESS" if success else "FAILED", output)

            # 3.3 Sentiment Analysis
            success, output = self.run_command_captured("classify_mentions_sentiment", limit=self.limit, model=self.ai_model, kind="both")
            self.log_step("Step 3.3: Sentiment", "SUCCESS" if success else "FAILED", output)

            # 4. Clustering (Now uses Topics + Entities from Step 3)
            # We assume clustering should not BLOCK pipeline unless catastrophic
            success, output = self.run_command_captured("cluster_articles_ai", hours=self.hours, limit=self.limit, dry_run=self.dry_run)
            self.log_step("Step 4: Clustering", "SUCCESS" if success else "FAILED", output)

            # 5. Synthesis (Digest)
            if not self.dry_run:
                self.log_step("Step 5: Synthesis", "STARTED")
                from monitor.models import DigestClient
                active_clients = DigestClient.objects.filter(is_active=True).select_related("config")
                
                if not active_clients.exists():
                    self.log_step("Step 5: Synthesis", "SKIPPED", "No active clients")
                
                digest_log = []
                for client in active_clients:
                    try:
                        config = client.config
                        print(f"Generating digest for: {client.name}")
                        
                        cmd_args = {
                            "title": config.title, 
                            "top": config.top_n,
                            "hours": config.hours or self.hours
                        }
                        
                        # Add Person IDs
                        p_ids = list(config.personas.values_list("id", flat=True))
                        # call_command kwargs must be specific types, but repeated args are tricky for call_command with dicts
                        # call_command handles list args differently in recent django versions or requires parse_args gymnastics
                        # EASIER: Build a list of args for call_command(*args)
                        
                        cli_args = [
                            "--title", config.title, 
                            "--top", str(config.top_n),
                            "--hours", str(config.hours or self.hours)
                        ]
                        for pid in p_ids: cli_args.extend(["--person-id", str(pid)])
                        i_ids = list(config.instituciones.values_list("id", flat=True))
                        for iid in i_ids: cli_args.extend(["--institution-id", str(iid)])
                        if config.topics:
                            topics_str = ",".join(config.topics)
                            cli_args.extend(["--topics", topics_str])

                        # Capture output for digest generation too
                        out = io.StringIO()
                        call_command("generate_client_digest", *cli_args, stdout=out)
                        digest_log.append(f"Client {client.name}: OK")
                        
                    except Exception as exc:
                        print(f"Error generating digest for {client.name}: {exc}")
                        digest_log.append(f"Client {client.name}: FAIL {exc}")

                # Apply AI Synthesis (Summaries)
                self.run_command_captured("create_digest_summary", model=self.ai_model)
                self.log_step("Step 5: Synthesis", "COMPLETED", "\n".join(digest_log))

            self._finish_run_tracking("success")
            print("--- Pipeline Completed Successfully ---")

        except Exception as e:
            print(f"Pipeline Failed: {e}")
            self._finish_run_tracking("failed", log=self.run_log) # Ensure full log is saved
            # re-raise to ensure calling process knows
            # raise e 
            pass

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
