from edusci.integrations.datasets.moe import MoeStatisticsAdapter
from edusci.integrations.datasets.unesco import UnescoUisAdapter
from edusci.integrations.datasets.unicef import UnicefSdmxAdapter
from edusci.integrations.datasets.world_bank import WorldBankAdapter

__all__ = [
    "MoeStatisticsAdapter",
    "UnescoUisAdapter",
    "UnicefSdmxAdapter",
    "WorldBankAdapter",
]


def default_dataset_adapters(client=None) -> list:
    return [
        WorldBankAdapter(client),
        UnicefSdmxAdapter(client),
        UnescoUisAdapter(client),
        MoeStatisticsAdapter(client),
    ]

