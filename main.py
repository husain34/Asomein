"""
main.py

Main Entry Point for Asomien Control Plane
"""

import argparse
import sys
import logging
import signal

from asomien.core.orchestrator import MasterOrchestrator
from asomien.human.cli import CLIController
from asomien.scheduler.jobs import SchedulerManager
from asomien.memory.engine import MemoryEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def handle_shutdown(signum, frame, orchestrator, apscheduler):
    logger.info("Received shutdown signal. Gracefully stopping...")
    if apscheduler and getattr(apscheduler, 'running', False):
        try:
            apscheduler.shutdown(wait=False)
        except Exception as e:
            logger.error("Error shutting down scheduler: %s", e)
    if orchestrator and hasattr(orchestrator, 'stop'):
        try:
            orchestrator.stop()
        except Exception as e:
            logger.error("Error shutting down orchestrator: %s", e)
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Asomien System Controller")
    parser.add_argument("--start", action="store_true", help="Start the master orchestrator daemon")
    parser.add_argument("--stop", action="store_true", help="Stop the daemon (requires PID management)")
    parser.add_argument("--status", action="store_true", help="Print system status")
    parser.add_argument("--approve", type=str, metavar="POST_ID", help="Approve a post by ID")
    parser.add_argument("--directive", type=str, metavar="TEXT", help="Add a human directive")
    parser.add_argument("--simulate", action="store_true", help="Force run the core loops immediately for testing")
    
    args = parser.parse_args()
    cli = CLIController()

    if args.status:
        cli.status()
        return

    if args.approve:
        cli.approve_post(args.approve)
        return

    if args.directive:
        cli.add_directive(args.directive)
        return

    if args.start:
        logger.info("Booting Asomien...")
        
        from asomien.memory.migrations import run_migrations
        run_migrations("data/memory.db")
        
        memory = MemoryEngine()
        
        # Instantiate Agents and Adapters
        from asomien.config.settings import settings
        from asomien.platforms.threads_adapter import ThreadsAdapter
        from asomien.agents.content_agent import ContentAgent
        from asomien.agents.critic_agent import CriticAgent
        from asomien.agents.engagement_agent import EngagementAgent
        from asomien.agents.research_agent import ResearchAgent
        from asomien.agents.analytics_agent import AnalyticsAgent
        
        from asomien.research.sources.ddg_source import DuckDuckGoSource
        from asomien.research.sources.tumblr_source import TumblrRSSSource
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        from asomien.research.sources.threads_keyword_source import ThreadsKeywordSource
        
        adapter = ThreadsAdapter(
            access_token=settings.threads_access_token,
            user_id=settings.threads_user_id
        )
        from asomien.llm.client import NIMClient
        nim_client = NIMClient(api_key=settings.nvidia_nim_api_key)
        content_agent = ContentAgent(memory=memory, llm_client=nim_client)
        critic_agent = CriticAgent(memory=memory, llm_client=nim_client)
        engagement_agent = EngagementAgent(adapter=adapter, memory=memory)
        
        ddg_source = DuckDuckGoSource()
        tumblr_source = TumblrRSSSource()
        kym_source = KnowYourMemeSource()
        threads_source = ThreadsKeywordSource(access_token=settings.threads_access_token)

        research_agent = ResearchAgent(
            memory=memory,
            ddg_source=ddg_source,
            tumblr_source=tumblr_source,
            kym_source=kym_source,
            threads_source=threads_source
        )
        analytics_agent = AnalyticsAgent(adapter=adapter)

        orchestrator = MasterOrchestrator(
            content_agent=content_agent,
            critic_agent=critic_agent,
            research_agent=research_agent,
            engagement_agent=engagement_agent,
            analytics_agent=analytics_agent,
            adapter=adapter,
            memory=memory
        )
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            apscheduler = BackgroundScheduler()
        except ImportError:
            apscheduler = None
            logger.warning("APScheduler not available, running without scheduled jobs.")
            
        scheduler = SchedulerManager(orchestrator=orchestrator, scheduler=apscheduler)
        
        signal.signal(signal.SIGINT, lambda s, f: handle_shutdown(s, f, orchestrator, apscheduler))
        signal.signal(signal.SIGTERM, lambda s, f: handle_shutdown(s, f, orchestrator, apscheduler))
        
        if hasattr(scheduler, "setup_jobs") and apscheduler:
            scheduler.setup_jobs(apscheduler, orchestrator)
        
        if apscheduler:
            apscheduler.start()
            
        orchestrator.start_loop()
        return

    if args.simulate:
        logger.info("Booting Asomien in SIMULATION mode...")
        
        from asomien.memory.migrations import run_migrations
        run_migrations("data/memory.db")
        
        memory = MemoryEngine()
        from asomien.config.settings import settings
        from asomien.platforms.threads_adapter import ThreadsAdapter
        from asomien.agents.content_agent import ContentAgent
        from asomien.agents.critic_agent import CriticAgent
        from asomien.agents.engagement_agent import EngagementAgent
        from asomien.agents.research_agent import ResearchAgent
        from asomien.agents.analytics_agent import AnalyticsAgent
        
        from asomien.research.sources.ddg_source import DuckDuckGoSource
        from asomien.research.sources.tumblr_source import TumblrRSSSource
        from asomien.research.sources.knowyourmeme_source import KnowYourMemeSource
        from asomien.research.sources.threads_keyword_source import ThreadsKeywordSource
        
        adapter = ThreadsAdapter(
            access_token=settings.threads_access_token,
            user_id=settings.threads_user_id
        )
        from asomien.llm.client import NIMClient
        nim_client = NIMClient(api_key=settings.nvidia_nim_api_key)
        content_agent = ContentAgent(memory=memory, llm_client=nim_client)
        critic_agent = CriticAgent(memory=memory, llm_client=nim_client)
        engagement_agent = EngagementAgent(adapter=adapter, memory=memory)
        
        ddg_source = DuckDuckGoSource()
        tumblr_source = TumblrRSSSource()
        kym_source = KnowYourMemeSource()
        threads_source = ThreadsKeywordSource(access_token=settings.threads_access_token)

        research_agent = ResearchAgent(
            memory=memory,
            ddg_source=ddg_source,
            tumblr_source=tumblr_source,
            kym_source=kym_source,
            threads_source=threads_source
        )
        analytics_agent = AnalyticsAgent(adapter=adapter)

        orchestrator = MasterOrchestrator(
            content_agent=content_agent,
            critic_agent=critic_agent,
            research_agent=research_agent,
            engagement_agent=engagement_agent,
            analytics_agent=analytics_agent,
            adapter=adapter,
            memory=memory
        )
        scheduler = SchedulerManager(orchestrator=orchestrator)
        
        logger.info("--- FORCING RESEARCH CYCLE ---")
        scheduler.job_research()
        logger.info("--- FORCING ENGAGEMENT CYCLE ---")
        scheduler.job_engage_replies()
        logger.info("--- FORCING PUBLISH CYCLE ---")
        scheduler.job_content_and_publish()
        logger.info("--- FORCING REFLECTION CYCLE ---")
        scheduler.job_reflect()
        
        logger.info("Simulation complete! Check logs/actions.log or your dashboard.")
        return

    if args.stop:
        logger.info("Stop command issued. Find the running PID and send SIGTERM.")
        return

    parser.print_help()

if __name__ == "__main__":
    main()
