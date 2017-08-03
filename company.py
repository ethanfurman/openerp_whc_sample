from openerp.osv import fields, osv

class res_company(osv.Model):
    _inherit = "res.company"
    _columns = {
            'sample_request_followers_ids': fields.many2many(
                'res.users',
                'sample_request_rescompany_rel',
                'sample_request_follower_cid',
                'sample_request_follower_uid',
                string='Auto-Followers',
                ),
            }
