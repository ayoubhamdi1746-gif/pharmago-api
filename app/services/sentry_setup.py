import structlog

logger = structlog.get_logger()


def init_sentry():
    try:
        from app.config import settings
        dsn = getattr(settings, "SENTRY_DSN", "")
        if dsn:
            import sentry_sdk
            from sentry_sdk.integrations.starlette import StarletteIntegration
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.structlog import StructlogIntegration

            sentry_sdk.init(
                dsn=dsn,
                integrations=[
                    StarletteIntegration(),
                    FastApiIntegration(),
                    StructlogIntegration(),
                ],
                traces_sample_rate=0.1,
                profiles_sample_rate=0.1,
                environment="production" if not settings.DEV_MODE else "development",
            )
            logger.info("sentry.initialized", dsn_prefix=dsn[:20])
        else:
            logger.info("sentry.not_configured")
    except ImportError:
        logger.info("sentry.sdk_not_installed")
    except Exception as e:
        logger.error("sentry.init_failed", error=str(e))
