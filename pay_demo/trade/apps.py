from django.apps import AppConfig


class TradeConfig(AppConfig):
    name = 'pay_demo.trade'
    verbose_name = "trade manage"

    def ready(self):
        try:
            import trade.signals  # noqa F401
        except ImportError:
            pass
