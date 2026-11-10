"""Historical parser/packing contracts, deliberately outside the job registry."""
from polymerhus.recon.domain.types import JobSpec,ConsumptionOptions,AssetSelector

def legacy_js_job(tool='jsluice'):
    return JobSpec(tool=tool,skill='js_secret_scan',command_template='',produces=['Endpoint','Secret'],
        consumes='Endpoint',consumes_where=AssetSelector(field='path',op='ends_with',values=['.js','.mjs']),
        consumption=ConsumptionOptions(pack='batches'))
