# -*- coding: utf-8 -*-

# imports
from fnx.oe import Proposed
from openerp import SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.exceptions import ERPError
import logging

_logger = logging.getLogger(__name__)

# selections
COMMON_SHIPPING = (
        ('fedex_first', 'FedEx First Overnight(early AM'),
        ('fedex_next', 'FedEx Next Overnight (late AM)'),
        ('fedex_overnight', 'FedEx Standard Overnight (early PM)'),
        ('fedex_2_am', 'FedEx 2-Day AM'),
        ('fedex_2_pm', 'FedEx 2-Day PM'),
        ('fedex_3', 'FedEx 3-Day (Express Saver)'),
        ('fedex_ground', 'FedEx Ground'),
        ('ups_first', 'UPS First Overnight'),
        ('ups_next', 'UPS Next Overnight (late AM)'),
        ('ups_overnight', 'UPS Overnight (late PM)'),
        ('ups_2', 'UPS 2-Day'),
        ('ups_3', 'UPS 3-Day'),
        ('ups_ground', 'UPS Ground'),
        ('ontrac_first', 'ONTRAC First Overnight'),
        ('ontrac_next', 'ONTRAC Next Overnight (early AM)'),
        ('ontrac_overnight', 'ONTRAC Overnight (late PM)'),
        ('ontrac_2', 'ONTRACK 2-Day'),
        ('dhl', 'DHL (give to receptionist)'),
        ('rep', 'Deliver to Sales Rep'),
        ('invoice', 'Ship with Invoice'),
        ('northbay', 'Falcon North Bay Truck'),
        )

REQUEST_SHIPPING = (
        ('cheap_1', 'Cheapest 1-Day'),
        ('cheap_2', 'Cheapest 2-Day'),
        ('cheap_3', 'Cheapest 3-Day'),
        ('cheap_ground', 'Cheapest Ground'),
        ) + COMMON_SHIPPING + (
        ('international', 'International (give to receptionist)'),
        )

# custom tables
class sample_request(osv.Model):
    _name = 'sample.request'
    _inherit = ['mail.thread']
    _order = 'state, create_date'
    _description = 'Sample Request'
    _rec_name = 'ref_name'

    _track = {
        'state' : {
            'sample.mt_sample_request_draft': lambda s, c, u, r, ctx: r['state'] == 'draft',
            'sample.mt_sample_request_production': lambda s, c, u, r, ctx: r['state'] == 'production',
            'sample.mt_sample_request_complete': lambda s, c, u, r, ctx: r['state'] == 'complete',
            }
        }

    _columns = {
        'state': fields.selection(
            (
                ('draft', 'Draft'),             # <- brand-spankin' new
                ('production', 'Production'),   # <- sales person clicked <Submit>
                ('complete', 'Complete'),       # <- someone said so
                ),
            string='Status',
            sort_order='definition',
            ),
        'ref_num': fields.char('Reference Sequence', size=12),
        'ref_name': fields.char('Reference Name', size=64),
        'user_id': fields.many2one('res.users', 'Request by', required=True, track_visibility='onchange'),
        'create_date': fields.datetime('Request created on', readonly=True, track_visibility='onchange'),
        'instructions': fields.text('Special Instructions', track_visibility='onchange'),
        'partner_id': fields.many2one('res.partner', 'Company', required=True, track_visibility='onchange'),
        'partner_is_company': fields.related('partner_id', 'is_company', type='boolean', string='Partner is Company'),
        'contact_id': fields.many2one('res.partner', 'Contact', track_visibility='onchange'),
        'contact_name': fields.related('contact_id', 'name', type='char', size=64, string='Contact Name'),
        'ship_to_id': fields.many2one('res.partner', 'Ship To', track_visiblility='onchange'),
        'submit_datetime': fields.datetime('Date Submitted', track_visibility='onchange'),
        # fields needed for shipping
        'address': fields.text(string='Shipping Label'),
        'address_type': fields.selection([('business', 'Commercial'), ('personal', 'Residential')], string='Address type', required=True, track_visibility='onchange'),
        'request_ship': fields.selection(REQUEST_SHIPPING, string='Ship Via', required=True, track_visibility='onchange'),
        'third_party_account': fields.char('3rd Party Account Number', size=64, track_visibility='onchange'),
        # products to sample
        'product_ids': fields.one2many('sample.product', 'request_id', string='Items', track_visibility='onchange'),
        }

    _defaults = {
        'user_id': lambda obj, cr, uid, ctx: uid,
        'address_type': 'business',
        'state': 'draft',
        }

    def button_sample_submit(self, cr, uid, ids, context=None):
        context = (context or {}).copy()
        context['sample_loop'] = True
        user = self.pool.get('res.users').browse(cr, uid, uid, context=context)
        values = {
                'state': 'new',
                'submit_datetime': fields.date.context_today(self, cr, uid, context=context),
                }
        follower_ids = [u.partner_id.id for u in user.company_id.sample_request_followers_ids]
        if follower_ids:
            self.message_subscribe(cr, uid, ids, follower_ids, context=context)
        return self.write(cr, uid, ids, values, context=context)

    def copy(self, cr, uid, id, default=None, context=None):
        default = (default or {}).copy()
        for setting, value in (
                ('state', 'draft'),
                ('submit_datetime', False),
                ):
            default[setting] = value
        original = self.browse(cr, uid, id, context=context)
        product_ids = []
        for p in original.product_ids:
            product_ids.append((
                0, 0, {
                'product_id': p.product_id.id,
                'product_lot_requested': p.product_lot_requested,
                }))
        default['product_ids'] = product_ids
        return super(sample_request, self).copy(cr, uid, id, default, context)

    def create(self, cr, uid, vals, context=None):
        ref_num = vals['ref_num'] = self.pool.get('ir.sequence').next_by_code(cr, uid, 'sample.request', context=context)
        partner = self.pool.get('res.partner').browse(cr, uid, vals['partner_id'], context=context)
        vals['ref_name'] = "%s - %s" % (ref_num, partner.name)
        return super(sample_request, self).create(cr, uid, vals, context)

    def name_get(self, cr, uid, ids, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = []
        for record in self.read(cr, uid, ids, fields=['id', 'partner_id'], context=context):
            id = record['id']
            name = (record['partner_id'] or (None, ''))[1]
            res.append((id, name))
        return res

    def _get_address(self, cr, uid, user_id, contact_id, partner_id, ship_to_id, context=None):
        res_partner = self.pool.get('res.partner')
        label = False
        if ship_to_id:
            ship_to = res_partner.browse(cr, uid, ship_to_id, context=context)
            label = ship_to.name + '\n' + res_partner._display_address(cr, uid, ship_to, context=context)
        elif contact_id:
            contact = res_partner.browse(cr, uid, contact_id, context=context)
            label = contact.name + '\n' + res_partner._display_address(cr, uid, contact, context=context)
        elif partner_id:
            partner = res_partner.browse(cr, uid, partner_id, context=context)
            label = partner.name + '\n' + res_partner._display_address(cr, uid, partner, context=context)
        return label

    def onchange_contact_id(self, cr, uid, ids, user_id, contact_id, partner_id, ship_to_id, context=None):
        res = {'value': {}, 'domain': {}}
        if contact_id:
            res_partner = self.pool.get('res.partner')
            contact = res_partner.browse(cr, uid, contact_id, context=context)
            if contact.is_company:
                # move into the partner_id field
                res['value']['partner_id'] = contact_id
                res['value']['contact_id'] = False
                res['domain']['contact_id'] = [('parent_id','=',contact.id)]
            elif contact.parent_id:
                # set the partner_id field with this parent
                res['value']['partner_id'] = contact.parent_id.id
                res['domain']['contact_id'] = [('parent_id','=',contact.parent_id.id)]
            else:
                # non-company person; shove value into partner
                res['value']['partner_id'] = contact.id
                res['value']['contact_id'] = False
                res['domain']['contact_id'] = []
        res['value']['address'] = self._get_address(cr, uid, user_id, contact_id, partner_id, ship_to_id, context=context)
        return res

    def onchange_partner_id(self, cr, uid, ids, user_id, contact_id, partner_id, ship_to_id, context=None):
        res = {'value': {}, 'domain': {}}
        if not partner_id:
            res['value']['contact_id'] = False
            res['domain']['contact_id'] = []
            res['value']['ship_to_id'] = False
            res['domain']['ship_to_id'] = []
        else:
            res_partner = self.pool.get('res.partner')
            partner = res_partner.browse(cr, uid, partner_id, context=context)
            if contact_id:
                contact = res_partner.browse(cr, uid, contact_id, context=context)
            if ship_to_id:
                ship_to = res_partner.browse(cr, uid, ship_to_id, context=context)
            # if is_company: set contact domain
            # elif has parent_id: make this the contact & set contact domain
            # else: blank contact, clear domain
            if partner.is_company:
                # this is a company
                res['domain']['contact_id'] = [('parent_id','=',partner.id)]
                if contact_id and contact.parent_id.id != partner.id:
                    res['value']['contact_id'] = False
            elif partner.parent_id:
                # this is a contact at a company
                res['value']['contact_id'] = partner_id
                res['value']['partner_id'] = partner_id = partner.parent_id.id
                res['domain']['contact_id'] = [('parent_id','=',partner_id)]
                partner = partner.parent_id
            else:
                # this is a non-company person
                res['value']['contact_id'] = False
                res['domain']['contact_id'] = []
            res['domain']['ship_to_id'] = [('ship_to_parent_id','=',partner.id)]
            if ship_to_id and ship_to.ship_to_parent_id != partner.id:
                res['value']['ship_to_id'] = False
        res['value']['address'] = self._get_address(cr, uid, user_id, contact_id, partner_id, ship_to_id, context=context)
        return res

    def onchange_partner_type(self, cr, uid, ids, partner_type, partner_id, context=None):
        res = {'value': {}, 'domain': {}}
        sample_partner_type = self.pool.get('sample.partner_type')
        domain = ''
        if partner_type:
            # find matching domain
            partner_type = sample_partner_type.read(cr, SUPERUSER_ID, [('id','=',partner_type)], fields=['partner_domain'], context=context)[0]
            domain = partner_type['partner_domain']
        else:
            # find default domain -- if none, use a default of all company customers
            default = sample_partner_type.read(cr, SUPERUSER_ID, [('default','=',True)], fields=['name','partner_domain'], context=context)
            if default:
                [default] = default
                domain = default['partner_domain']
                res['value']['partner_type'] = default['id']
            else:
                domain = "[('is_company','=',1),('customer','=',1)]"
        if partner_id:
            # ensure current partner meets new domain requirements
            res_partner = self.pool.get('res.partner')
            check_partner = eval(domain) + [('id','=',partner_id)]
            matches = res_partner.search(cr, uid, check_partner, context=context)
            if not matches:
                res['value']['partner_id'] = False
        res['domain']['partner_id'] = domain
        return res

    def onchange_ship_to_id(self, cr, uid, ids, user_id, contact_id, partner_id, ship_to_id, context=None):
        res = {'value': {}, 'domain': {}}
        res['value']['address'] = self._get_address(cr, uid, user_id, contact_id, partner_id, ship_to_id, context=context)
        return res

    # def onchange_send_to(self, cr, uid, ids, user_id, contact_id, partner_id, request_ship, context=None):
    #     res = {'value': {}, 'domain': {}}
    #     res['value']['address'] = self._get_address(cr, uid, user_id, contact_id, partner_id, context=context)
    #     if send_to == 'rep' and not request_ship:
    #         res['value']['request_ship'] = 'rep'
    #     elif request_ship == 'rep':
    #         res['value']['request_ship'] = False
    #     return res

    def onload(self, cr, uid, ids, user_id, contact_id, partner_id, context=None):
        partner_id_res = self.onchange_partner_id(cr, uid, ids, user_id, contact_id, partner_id, context=context)
        partner_type_res = self.onchange_partner_type(cr, uid, ids, 0, partner_id, context=context)
        res = partner_id_res.copy()
        res['value'].update(partner_type_res['value'])
        res['domain'].update(partner_type_res['domain'])
        return res

    def unlink(self, cr, uid, ids, context=None):
        #
        # only allow if one of:
        # - uid is owner
        # - uid is manager
        # and
        # - request is Draft or Submitted (not Production, Transit, or Received)
        #
        res_users = self.pool.get('res.users')
        user = res_users.browse(cr, uid, uid, context=context)
        manager = user.has_group('base.group_sale_manager') or user.has_group('sample.group_sample_manager')
        if isinstance(ids, (int, long)):
            ids = [ids]
        for request in self.read(cr, uid, ids, fields=['user_id', 'state'], context=context):
            if not manager and request['state'] not in ('draft', 'new'):
                raise ERPError('Bad Status', 'can only delete requests that are Draft or Submitted')
            elif not manager and request['user_id'][0] != uid:
                raise ERPError('Permission Denied', 'You may only delete your own requests')
        else:
            super(sample_request, self).unlink(cr, uid, ids, context=context)

    def write(self, cr, uid, ids, values, context=None):
        if context is None:
            context = {}
        if ids and not context.get('sample_loop'):
            if isinstance(ids, (int, long)):
                ids = [ids]
            user = self.pool.get('res.users').browse(cr, uid, uid, context=context)
            for record in self.browse(cr, SUPERUSER_ID, ids, context=context):
                vals = values.copy()
                proposed = Proposed(self, cr, values, record, context=context)
                if 'state' not in vals:
                    state = 'draft'
                    old_state = record.state
                    if record.state == 'draft' and state not in ('draft', ):
                        # make sure 'submit' happens before other, later, states
                        self.button_sample_submit(cr, uid, ids, context=context)
                    if proposed.state != state:
                        proposed.state = vals['state'] = state
                    if 'product_ids' in vals and old_state != 'draft':
                        if not user.has_group('sample.group_sample_user'):
                            raise ERPError('Error', 'Order has already been submitted.  Talk to someone in Samples to get more products added.')
                if proposed.state != 'draft' and not proposed.product_ids:
                    raise ERPError('Missing Products', 'Sample request has no products listed!')
                super(sample_request, self).write(cr, uid, [record.id], vals, context=context)
            return True
        return super(sample_request, self).write(cr, uid, ids, values, context=context)


class sample_product(osv.Model):
    _name = 'sample.product'

    _columns = {
        'name': fields.related('product_id', 'name'),
        'request_id': fields.many2one('sample.request', string='Request'),
        'request_state': fields.related('request_id','state', type='char'),
        'product_id': fields.many2one('product.product', string='Item', domain=[('categ_id','child_of','Saleable')]),
        'product_lot_requested': fields.char('Lot # Requested', size=24),
        'product_lot_used': fields.char('Lot # Used', size=24, oldname='product_lot'),
        }

    def button_same_lot_no(self, cr, uid, ids, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        for product in self.read(cr, uid, ids, fields=['id', 'product_lot_requested'], context=context):
            self.write(
                    cr, uid,
                    product['id'],
                    {'product_lot_used': product['product_lot_requested']},
                    context=context,
                    )
