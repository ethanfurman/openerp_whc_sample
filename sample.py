# -*- coding: utf-8 -*-

# imports
from dbf import Date, DateTime
from fnx.oe import Proposed
from openerp import SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.exceptions import ERPError
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT
from scripts.sample import split_label
from VSS.finance import FederalHoliday
from VSS.utils import contains_any
import logging

_logger = logging.getLogger(__name__)

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

shipping_urls = {
        'fedex':  'https://www.fedex.com/apps/fedextrack/?tracknumbers=%s&cntry_code=us',
        'ups':    'https://wwwapps.ups.com/WebTracking/track?track=yes&trackNums=%s',
        'ontrac': 'https://www.ontrac.com/trackingres.asp?tracking_number=%s',
        'dhl':    'http://webtrack.dhlglobalmail.com/?trackingnumber=%s',
        'usps':   'https://tools.usps.com/go/TrackConfirmAction_input?origTrackNum=%s',
        }

# custom tables
class sample_request(osv.Model):
    _name = 'sample.request'
    _inherit = ['mail.thread']
    _order = 'state, create_date'
    _description = 'Sample Request'

    _track = {
        'state' : {
            'sample.mt_sample_request_draft': lambda s, c, u, r, ctx: r['state'] == 'draft',
            'sample.mt_sample_request_new': lambda s, c, u, r, ctx: r['state'] == 'new',
            'sample.mt_sample_request_production': lambda s, c, u, r, ctx: r['state'] == 'production',
            'sample.mt_sample_request_ready': lambda s, c, u, r, ctx: r['state'] == 'shipping',
            'sample.mt_sample_request_transiting': lambda s, c, u, r, ctx: r['state'] == 'transit',
            'sample.mt_sample_request_received': lambda s, c, u, r, ctx: r['state'] == 'complete',
            }
        }

    # def __init__(self, pool, cr):
    #     'update send_to data'
    #     cr.execute("UPDATE sample_request SET send_to='customer' WHERE send_to='address'")
    #     return super(sample_request, self).__init__(pool, cr)

    def _get_pdf(self, cr, uid, ids, field_name, arg, context=None):
        res = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        dbname = cr.dbname
        if ids:
            for id in ids:
                res[id] = '<a href="/samplerequest/%s/SampleRequest_%d.pdf">Printer Friendly</a>' % (dbname, id)
        return res

    def _get_rush(self, cr, uid, ids, field_name, arg, context=None):
        # for target date type of 'shipping', less than three business days is a RUSH
        # for target date type of 'arrive', 1, 2, and 3 day shipping are subtracted from
        # total business days, and less than three is a RUSH
        res = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        for data_rec in self.read(
                cr, uid, ids,
                ['id', 'actual_ship_date', 'create_date', 'request_ship', 'state', 'submit_datetime', 'target_date', 'target_date_type'],
                context=context,
                ):
            if data_rec['actual_ship_date'] or not data_rec['submit_datetime']:
                # order has shipped, or not been submitted yet
                text = False
            elif data_rec['state'] not in ('production', 'shipping'):
                # once it's on its way we can no longer affect it
                text = False
            else:
                # order has been submitted, request_ship may have changed
                in_plant_days_limit = 3
                starting_date = data_rec['submit_datetime']
                days_available = FederalHoliday.count_business_days(
                        DateTime(starting_date).date(),
                        Date(data_rec['target_date']),
                        )
                if data_rec['target_date_type'] == 'arrive':
                    if contains_any(data_rec['request_ship'], 'first', 'next', 'overnight', '1'):
                        days_available -= 1
                    elif contains_any(data_rec['request_ship'], '2'):
                        days_available -= 2
                    elif contains_any(data_rec['request_ship'], '3'):
                        days_available -= 3
                if days_available < in_plant_days_limit:
                    text = 'R U S H'
                else:
                    text = False
            res[data_rec['id']] = text
        return res

    def _get_target_date(self, cr, uid, context=None):
        # get the next third business day
        today = Date.strptime(
                fields.date.context_today(self, cr, uid, context=context),
                DEFAULT_SERVER_DATE_FORMAT,
                )
        target = FederalHoliday.next_business_day(today, days=3)
        return target.strftime(DEFAULT_SERVER_DATE_FORMAT)

    def _get_tracking_url(self, cr, uid, ids, field_name, arg, context=None):
        res = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        for row in self.read(cr, uid, ids, fields=['id', 'actual_ship', 'tracking'], context=context):
            id = row['id']
            tracking_no = row['tracking']
            shipper = row['actual_ship']
            res[id] = False
            if shipper and tracking_no:
                shipper = shipper.split('_')[0]
                res[id] = '<a href="%s" target="_blank">%s</a>' % (shipping_urls[shipper] % tracking_no, tracking_no)
        return res

    _columns = {
        'state': fields.selection(
            (
                ('draft', 'Draft'),             # <- brand-spankin' new
                ('new', 'Submitted'),           # <- sales person clicked on submit
                ('production', 'Production'),   # <- julian_date_code set
                ('shipping', 'Ready to Ship'),  # <- all product_lot's filled in
                ('transit', 'In Transit'),      # <- tracking number entered
                ('complete', 'Received'),       # <- received_datetime entered
                ),
            string='Status',
            sort_order='definition',
            ),
        'department': fields.selection([('marketing', 'SAMMA - Marketing'), ('sales', 'SAMSA - Sales')], string='Department', required=True, track_visibility='onchange'),
        'user_id': fields.many2one('res.users', 'Request by', required=True, track_visibility='onchange'),
        'for_user_id': fields.many2one('res.users', 'Request for', track_visibility='onchange'),
        'partner_type': fields.many2one('sample.partner_type', 'Filter', track_visibility='onchange'),
        'create_date': fields.datetime('Request created on', readonly=True, track_visibility='onchange'),
        'send_to': fields.selection([('rep', 'Sales Rep'), ('customer', 'Customer')], string='Send to', required=True, track_visibility='onchange'),
        'target_date_type': fields.selection([('ship', 'Ship'), ('arrive', 'Arrive')], string='Samples must', required=True, track_visibility='onchange'),
        'target_date': fields.date('Target Date', required=True, track_visibility='onchange'),
        'rush': fields.function(
            _get_rush,
            type='char',
            size=10,
            store={
                'sample.request': (
                    lambda k, c, u, ids, ctx: ids,
                    ['request_ship', 'state', 'submit_datetime', 'target_date', 'target_date_type'],
                    10,
                    )
                },
            ),
        'instructions': fields.text('Special Instructions', track_visibility='onchange'),
        'partner_id': fields.many2one('res.partner', 'Company', track_visibility='onchange'),
        'partner_is_company': fields.related('partner_id', 'is_company', type='boolean', string='Partner is Company'),
        'contact_id': fields.many2one('res.partner', 'Contact', track_visibility='onchange'),
        'contact_name': fields.related('contact_id', 'name', type='char', size=64, string='Contact Name'),
        'rep_time': fields.float("Rep's Time"),
        'submit_datetime': fields.datetime('Date Submitted', track_visibility='onchange'),
        # fields needed for shipping
        'address': fields.text(string='Shipping Label'),
        'address_type': fields.selection([('business', 'Commercial'), ('personal', 'Residential')], string='Address type', required=True, track_visibility='onchange'),
        'ice': fields.boolean('Add ice', track_visibility='onchange'),
        'request_ship': fields.selection(REQUEST_SHIPPING, string='Ship Via', required=True, track_visibility='onchange'),
        'ship_early': fields.boolean('Okay to ship early', choice=('', '(or earlier)')),
        'actual_ship': fields.selection(COMMON_SHIPPING, string='Actual Shipping Method', track_visibility='onchange'),
        'actual_ship_date': fields.date('Shipped on', track_visibility='onchange'),
        'third_party_account': fields.char('3rd Party Account Number', size=64, track_visibility='onchange'),
        'tracking': fields.char('Tracking #', size=32, track_visibility='onchange'),
        'tracking_url': fields.function(_get_tracking_url, type='char', size=256, string='Tracking #', store=False),
        'shipping_cost': fields.float('Shipping Cost', track_visibility='onchange'),
        'received_by': fields.char('Received by', size=32, track_visibility='onchange'),
        'received_datetime': fields.datetime('Received when', track_visibility='onchange'),
        # field for samples department only
        'invoice': fields.char('Invoice #', size=32, track_visibility='onchange'),
        'julian_date_code': fields.char('Julian Date Code', size=12, track_visibility='onchange'),
        'production_order': fields.char('Production Order #', size=12, track_visibility='onchange'),
        'prep_time': fields.float('Preparation Time'),
        'finish_date': fields.date('Sample Packaged Date', track_visibility='onchange'),
        # products to sample
        'product_ids': fields.one2many('sample.product', 'request_id', string='Items', track_visibility='onchange'),
        # link to printer-friendly form
        'printer_friendly': fields.function(_get_pdf, type='html', store=False),
        }

    _defaults = {
        'user_id': lambda obj, cr, uid, ctx: uid,
        'address_type': 'business',
        'state': 'draft',
        'target_date': _get_target_date,
        }

    _user_defaultable = [
        'department', 'for_user_id', 'partner_type', 'send_to', 'target_date_type', 'instructions',
        'address_type', 'ice', 'request_ship',
        ('product_ids', ['product_id', 'product_lot_requested', 'qty_id']),
        ('message_follower_ids', ['name']),
        ]

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
                ('target_date', self._get_target_date(cr, uid, context=context)),
                ('rush', False),
                ('rep_time', False),
                ('submit_datetime', False),
                ('ship_early', False),
                ('actual_ship', False),
                ('actual_ship_date', False),
                ('tracking', False),
                ('tracking_url', False),
                ('shipping_cost', False),
                ('received_by', False),
                ('received_datetime', False),
                ('invoice', False),
                ('julian_date_code', False),
                ('production_order', False),
                ('prep_time', False),
                ('finish_date', False),
                ):
            default[setting] = value
        original = self.browse(cr, uid, id, context=context)
        product_ids = []
        for p in original.product_ids:
            product_ids.append((
                0, 0, {
                'qty_id': p.qty_id.id,
                'product_id': p.product_id.id,
                'product_lot_requested': p.product_lot_requested,
                }))
        default['product_ids'] = product_ids
        return super(sample_request, self).copy(cr, uid, id, default, context)

    def name_get(self, cr, uid, ids, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = []
        for record in self.read(cr, uid, ids, fields=['id', 'partner_id'], context=context):
            id = record['id']
            name = (record['partner_id'] or (None, ''))[1]
            res.append((id, name))
        return res

    def _get_address(self, cr, uid, send_to, user_id, contact_id, partner_id, context=None):
        res_partner = self.pool.get('res.partner')
        if send_to == 'rep':
            # stuff the rep's address into the record
            user = self.pool.get('res.users').browse(cr, uid, user_id, context=context)
            rep = user.partner_id
            label = rep.name + '\n' + res_partner._display_address(cr, uid, rep, context=context)
        elif send_to:
            label = False
            if contact_id:
                contact = res_partner.browse(cr, uid, contact_id, context=context)
                label = contact.name + '\n' + res_partner._display_address(cr, uid, contact, context=context)
            elif partner_id:
                partner = res_partner.browse(cr, uid, partner_id, context=context)
                label = partner.name + '\n' + res_partner._display_address(cr, uid, partner, context=context)
        else:
            label = False
        return label

    def onchange_contact_id(self, cr, uid, ids, send_to, user_id, contact_id, partner_id, context=None):
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
        res['value']['address'] = self._get_address(cr, uid, send_to, user_id, contact_id, partner_id, context=context)
        return res

    def onchange_partner_id(self, cr, uid, ids, send_to, user_id, contact_id, partner_id, context=None):
        res = {'value': {}, 'domain': {}}
        if not partner_id:
            res['value']['contact_id'] = False
            res['domain']['contact_id'] = []
        else:
            res_partner = self.pool.get('res.partner')
            partner = res_partner.browse(cr, uid, partner_id, context=context)
            if contact_id:
                contact = res_partner.browse(cr, uid, contact_id, context=context)
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
                res['value']['partner_id'] = partner.parent_id.id
                res['domain']['contact_id'] = [('parent_id','=',partner.parent_id.id)]
            else:
                # this is a non-company person
                res['value']['contact_id'] = False
                res['domain']['contact_id'] = []

        res['value']['address'] = self._get_address(cr, uid, send_to, user_id, contact_id, partner_id, context=context)
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

    def onchange_send_to(self, cr, uid, ids, send_to, user_id, contact_id, partner_id, request_ship, context=None):
        res = {'value': {}, 'domain': {}}
        res['value']['address'] = self._get_address(cr, uid, send_to, user_id, contact_id, partner_id, context=context)
        if send_to == 'rep' and not request_ship:
            res['value']['request_ship'] = 'rep'
        elif request_ship == 'rep':
            res['value']['request_ship'] = False
        return res

    def onload(self, cr, uid, ids, send_to, user_id, contact_id, partner_id, context=None):
        partner_id_res = self.onchange_partner_id(cr, uid, ids, send_to, user_id, contact_id, partner_id, context=context)
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
                    state = 'draft' if proposed.state == 'draft' else 'new'
                    old_state = record.state
                    if any([proposed.invoice, proposed.julian_date_code, proposed.production_order]):
                        state = 'production'
                    if proposed.product_ids:
                        for sample_product in proposed.product_ids:
                            if not sample_product.product_lot_used:
                                break
                        else:
                            state = 'shipping'
                    if proposed.finish_date:
                        state = 'shipping'
                    if any([proposed.actual_ship, proposed.actual_ship_date, proposed.tracking]):
                        state = 'transit'
                    if any([proposed.received_by, proposed.received_datetime]):
                        state = 'complete'
                    if record.state == 'draft' and state not in ('draft', 'new'):
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

class sample_partner_type(osv.Model):
    _name = 'sample.partner_type'
    _order = 'name'

    _columns = {
        'active': fields.boolean('Active'),
        'name': fields.char('Description'),
        'partner_domain': fields.text('Domain to match'),
        'default': fields.boolean('Default', help='Use this domain as the default domain'),
        }

    _defaults = {
        'active': True,
        }


class sample_qty_label(osv.Model):
    _name = 'sample.qty_label'
    _order = 'common desc, name asc'

    _columns = {
        'name': fields.char('Qty Label', size=16, required=True),
        'common': fields.boolean('Commonly Used Size'),
        }

    def create(self, cr, uid, values, context=None):
        "only create unique versions of name, returning existing versions instead"
        if 'name' not in values:
            return super(sample_qty_label, self).create(cr, uid, values, context=context)
        name = split_label(values['name'])
        if name.startswith('error'):
            raise ERPError('Error', '%s is invalid' % values['name'])
        matches = self.read(cr, uid, [('name','=',name)], fields=['id', 'name'], context=context)
        matches.sort(key=lambda m: m['id'])
        if matches:
            return matches[0]['id']
        else:
            values['name'] = name
            return super(sample_qty_label, self).create(cr, uid, values, context=context)


class sample_product(osv.Model):
    _name = 'sample.product'

    _columns = {
        'name': fields.related('product_id', 'name'),
        'request_id': fields.many2one('sample.request', string='Request'),
        'request_state': fields.related('request_id','state', type='char'),
        'qty_id': fields.many2one('sample.qty_label', string='Qty', oldname='qty'),
        'product_id': fields.many2one('product.product', string='Item', domain=[('categ_id','child_of','Saleable')]),
        'product_lot_requested': fields.char('Lot # Requested', size=24),
        'product_lot_used': fields.char('Lot # Used', size=24, oldname='product_lot'),
        'product_cost': fields.float('Retail Price'),
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
