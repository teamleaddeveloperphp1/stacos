from dataclasses import dataclass


@dataclass(frozen=True)
class Service:
    slug: str
    name: str
    description: str
    icon: str
    available: bool
    url_name: str | None = None  # reversed only when available


# Single source of truth -- the dashboard, the coming-soon page, and any
# future launch all read from this list. Adding a service later means
# editing one entry here, nothing else.
CATALOG = [
    Service(
        slug='tds-itr',
        name='TDS, ITR',
        description='Prepare, validate and file ITR-1 returns.',
        icon='📄',
        available=True,
        url_name='itr:return_list',
    ),
    Service(
        slug='esic',
        name='ESIC Compliance',
        description='Employee State Insurance compliance filings.',
        icon='🏥',
        available=False,
    ),
    Service(
        slug='epf',
        name='EPF Compliance',
        description='Employee Provident Fund compliance filings.',
        icon='🏦',
        available=False,
    ),
    Service(
        slug='cma',
        name='Credit Monitoring Arrangement',
        description='CMA data preparation for bank credit reviews.',
        icon='📊',
        available=False,
    ),
    Service(
        slug='project-financing',
        name='Project Financing',
        description='Project finance documentation and workflows.',
        icon='🏗️',
        available=False,
    ),
]

CATALOG_BY_SLUG = {s.slug: s for s in CATALOG}


def get_service(slug):
    return CATALOG_BY_SLUG.get(slug)
