import logging
from osv import osv, fields

_logger = logging.getLogger(__name__)

class res_partner(osv.Model):
    """
    Inherits partner and adds links to sample requests
    """
    _name = 'res.partner'
    _inherit = 'res.partner'

    _columns = {
        'sample_request_ids': fields.one2many(
            'sample.request', 'partner_id',
            string='Sample Requests',
            domain=[('state','!=','complete')],
            ),
        }
