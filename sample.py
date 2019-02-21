# -*- coding: utf-8 -*-

# imports
from fnx.oe import Proposed
from openerp import SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.exceptions import ERPError
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT
import datetime
import logging
from printcap import Oki380

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
    def _changed_res_partner_phone_ids(res_partner, cr, uid, changed_ids, context=None):
        #
        # changed_ids are all the res.partner records with changed phone
        # numbers; need to return the sample.request record ids that reference
        # those res.partner records (kept in partner_id and contact_id)
        #
        self = res_partner.pool.get('sample.request')
        ids = self.search(
                cr, uid,
                ['|',('partner_id','in',changed_ids),('contact_id','in',changed_ids)],
                context=context,
                )
        return ids

    def _get_address(
            self, cr, uid,
            user_id, contact_id, partner_id, ship_to_id,
            request_type, lead_id, lead_company, lead_name,
            context=None,
            ):
        res_partner = self.pool.get('res.partner')
        label = False
        if lead_id:
            crm_lead = self.pool.get('crm.lead')
            lead = crm_lead.browse(cr, uid, lead_id, context=context)
            label = ''
            if lead_name:
                label += lead_name + '\n'
            label += crm_lead._display_address(cr, uid, lead, context=context)
        elif contact_id:
            contact = res_partner.browse(cr, uid, contact_id, context=context)
            label = contact.name + '\n' + res_partner._display_address(cr, uid, contact, context=context)
        elif partner_id:
            partner = res_partner.browse(cr, uid, partner_id, context=context)
            label = partner.name + '\n' + res_partner._display_address(cr, uid, partner, context=context)
        return label

    def _get_phone(self, cr, uid, links, context=None):
        for table, id in links:
            if not id:
                continue
            table = self.pool.get(table)
            data = table.read(cr, SUPERUSER_ID, id, fields=['phone'], context=context)
            if data['phone']:
                return data['phone']
        return False

    def _get_telephone_nos(self, cr, uid, ids, field_name, arg, context=None):
        res = {}
        if field_name != 'phone':
            return res
        # get changed records
        for rec in self.browse(cr, uid, ids, context=context):
            id = rec.id
            for field in ('contact_id', 'lead_id', 'partner_id'):
                if rec[field] and rec[field].phone:
                    res[id] = rec[field].phone
                    break
            else:
                res[id] = False
        return res

    def _get_tree_contacts(self, cr, uid, ids, field_names, arg, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = {}
        for sample in self.browse(cr, uid, ids, context=context):
            if sample.request_type == 'lead':
                contact = sample.lead_name or sample.lead_id.name
                company = sample.lead_company or sample.lead_id.partner_id.name or sample.lead_id.name
                if contact in (company, None):
                    contact = False
                if company is None:
                    company = False
            elif sample.request_type == 'customer':
                contact = sample.contact_id.name
                company = sample.partner_id.name
            res[sample.id] = {'tree_contact': contact, 'tree_company': company}
        return res

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
        'partner_id': fields.many2one('res.partner', 'Company', required=False, track_visibility='onchange'),
        'partner_is_company': fields.related('partner_id', 'is_company', type='boolean', string='Partner is Company'),
        'lead_name': fields.related('lead_id', 'contact_name', string='Contact', type='char', size=64),
        'lead_company': fields.related('lead_id', 'partner_name', string='Contact Company', type='char', size=64),
        'lead_id': fields.many2one('crm.lead', 'Lead', track_visibility='onchange', ondelete='restrict'),
        'contact_id': fields.many2one('res.partner', 'Contact', track_visibility='onchange'),
        'contact_name': fields.related('contact_id', 'name', type='char', size=64, string='Contact Name'),
        'phone': fields.function(
            _get_telephone_nos,
            type='char',
            size=32,
            string='Telephone',
            store={
                'sample.request': (lambda k, c, u, ids, ctx: ids, ['partner_id', 'contact_id'], 10),
                'res.partner': (_changed_res_partner_phone_ids, ['phone'], 20),
                },
            ),
        'ship_to_id': fields.many2one('res.partner', 'Ship To', track_visiblility='onchange'),
        'request_type': fields.selection(
            [('customer', 'Existing Customer'), ('lead', 'New Customer')],
            string='Request Type', track_visibility='onchange',
            ),
        'tree_contact': fields.function(
            _get_tree_contacts, type='char', size=64, multi='tree', string='Tree Contact',
            store = {'sample.request': (lambda table, cr, uid, ids, ctx=None: ids, ['contact_id', 'lead_id', 'partner_id'], 10)},
            ),
        'tree_company': fields.function(
            _get_tree_contacts, type='char', size=64, multi='tree', string='Tree Company',
            store = False,
            # store={'sample.request': (lambda table, cr, uid, ids, ctx=None: ids, ['contact_id', 'lead_id', 'partner_id'], 10)},
            ),
        'submit_datetime': fields.datetime('Date Submitted', track_visibility='onchange'),
        # fields needed for shipping
        'address': fields.text(string='Shipping Label'),
        'address_type': fields.selection([('business', 'Commercial'), ('personal', 'Residential')], string='Address type', required=True, track_visibility='onchange'),
        'request_ship': fields.selection(REQUEST_SHIPPING, string='Ship Via', required=True, track_visibility='onchange'),
        'third_party_account': fields.char('3rd Party Account Number', size=64, track_visibility='onchange'),
        # products to sample
        'product_ids': fields.one2many('sample.product', 'request_id', string='Items', track_visibility='onchange'),
        'lot_labels': fields.text('Lot # labels'),
        }

    _defaults = {
        'user_id': lambda obj, cr, uid, ctx: uid,
        'address_type': 'business',
        'state': 'draft',
        'request_type': 'customer',
        }

    def button_sample_complete(self, cr, uid, ids, context=None):
        context = (context or {}).copy()
        context['sample_loop'] = True
        if isinstance(ids, (int, long)):
            ids = [ids]
        today = datetime.datetime.strptime(
                fields.date.today(self, cr, localtime=True),
                DEFAULT_SERVER_DATE_FORMAT,
                ).date().today.strftime('%m/%d/%Y')
        labels = []
        for sample in self.browse(cr, uid, ids, context=context):
            for product in sample.product_ids:
                code = product.default_code.strip()
                name = product.product_tmpl_id.name.strip()
                if code:
                    desc = "[%s] %s" % (code, name)
                else:
                    desc = name
                labels.append(
                        'ref: %s\n'
                        'date: %s\n'
                        'prod: %s\n'
                        'lot: %s'
                        % (
                            sample.ref_num,
                            today,
                            desc,
                            product.product_lot_used,
                            ))
            values = {
                'state': 'complete',
                'lot_labels': '\f'.join(labels),
                }
            self.write(cr, uid, ids, values, context=context)
        self.button_sample_reprint(cr, uid, ids, context=context)
        return True

    def button_sample_reprint(self, cr, uid, ids, context=None):
        def _format_description(desc, cpl, context=None):
            # build description
            # split description if necessary
            width = _width(desc)
            if width > cpl:
                # too big for one line, split it
                old_desc = desc
                desc = ''
                line_width = 0
                for word in old_desc.split():
                    if not line_width:
                        desc = word[:cpl]
                        line_width = len(desc) + 1
                        continue
                    word_width = _width(word)
                    if line_width + word_width > cpl:
                        word = word[:cpl]
                        desc += '\n%s' % word
                        line_width = len(word) + 1
                        continue
                    desc += '%s %s' % (desc, word)
                    line_width += word_width + 1
            # return description
            return desc
        def _width(word):
            narrow = "1iltfj!"
            wide = "WM"
            width = len(word)
            for ch in narrow:
                width -= word.count(ch) * 0.5
            for ch in wide:
                width += word.count(ch) * 1.5
            return width
        def _create_label(data, cpl, context=None):
            """
            Sample: [number]   [date]
            [description]
            [lot number]
            """
            ref = data['ref']
            date = data['date']
            prod = data['prod']
            lot = data['lot']
            label = []
            label.extend([
                    "Sample: {bold}%s{justify:right}%s{/bold}\n\n" % (ref, date),
                    "{justify:left}{bold}",
                    _format_description(prod, cpl, context=context),
                    "{/bold}\n\n",
                    "Lot #: {bold}%s{/bold}" % lot,
                    ])
            label = ''.join(label)
            label = label.replace('\n\n', '{cr}{lf}{lf}')
            label = label.replace('\n', '{cr}{lf}')
            return label
        def _label_dict(data):
            res = {}
            for line in data.strip().split('\n'):
                if not line.strip():
                    continue
                key, value = line.split(':', 1)
                res[key.strip()] = value.strip()
            return res
        #
        if isinstance(ids, (int, long)):
            ids = [ids]
        header = (
                "{reset}{form:6,18}{font:lq,roman,12}{margins:4,38}"
                + "{lf}" * 5
                )
        for sample in self.browse(cr, uid, ids, context=context):
            ref_num = sample.ref_num
            # generate plain-text version
            with open('/opt/openerp/var/sample_labels/%s.txt' % ref_num, 'w') as label:
                label.write(sample.lot_labels)
            # generate custom Okidata version
            label_data = [
                    _label_dict(l)
                    for l in sample.lot_labels.split('\f')
                    ]
            labels = [
                _create_label(lbl, cpl=34, context=context)
                for lbl in label_data
                ]
            labels = header + ('{ff}'+'{lf}'*5).join(labels)
            with open('/opt/openerp/var/sample_labels/%s.prn' % ref_num, 'w') as label:
                label.write(Oki380().transform(labels))
        return True

    def button_sample_submit(self, cr, uid, ids, context=None):
        context = (context or {}).copy()
        context['sample_loop'] = True
        user = self.pool.get('res.users').browse(cr, uid, uid, context=context)
        values = {
                'state': 'production',
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
        for record in self.read(
                cr, uid, ids,
                fields=['id', 'partner_id', 'request_type', 'lead_id'],
                context=context,
                ):
            id = record['id']
            if record['request_type'] == 'lead':
                name = (record['lead_id'] or (None, ''))[1]
            elif record['request_type'] == 'customer':
                name = (record['partner_id'] or (None, ''))[1]
            else:
                raise ERPError('unknown request type: %r' % (record['request_type'], ))
            res.append((id, name))
        return res

    def onchange_contact_id(
            self, cr, uid, ids,
            user_id, contact_id, partner_id, ship_to_id,
            request_type, lead_id, lead_company, lead_name,
            context=None,
            ):
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
        res['value']['address'] = self._get_address(
                cr, uid,
                user_id, contact_id, partner_id, ship_to_id,
                request_type, lead_id, lead_company, lead_name,
                context=context,
                )
        res['value']['phone'] = self._get_phone(
                cr, uid,
                (('res.partner', contact_id), ('crm.lead', lead_id), ('res.partner', partner_id)),
                context=context,
                )
        return res

    def onchange_lead_id(
            self, cr, uid, ids,
            user_id, contact_id, partner_id, ship_to_id,
            request_type, lead_id, lead_company, lead_name,
            context=None,
            ):
        res = {'value': {}}
        if lead_id:
            crm_lead = self.pool.get('crm.lead')
            lead = crm_lead.browse(cr, uid, lead_id, context=context)
            lead_partner = lead.partner_id
            lead_company = res['value']['lead_company'] = lead.partner_name
            lead_name = res['value']['lead_name'] = lead.contact_name
            if partner_id != lead_partner.id:
                partner_id = res['value']['partner_id'] = lead_partner.id
            if contact_id:
                contact_id = res['value']['contact_id'] = False
        else:
            lead_company = res['value']['lead_company'] = False
            lead_name = res['value']['lead_name'] = False
        res['value']['address'] = self._get_address(
                cr, uid,
                user_id, contact_id, partner_id, ship_to_id,
                request_type, lead_id, lead_company, lead_name,
                context=context,
                )
        res['value']['phone'] = self._get_phone(
                cr, uid,
                (('res.partner', contact_id), ('crm.lead', lead_id), ('res.partner', partner_id)),
                context=context,
                )
        return res

    def onchange_partner_id(
            self, cr, uid, ids,
            user_id, contact_id, partner_id, ship_to_id,
            request_type, lead_id, lead_company, lead_name,
            context=None,
            ):
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
        res['value']['address'] = self._get_address(
                cr, uid,
                user_id, contact_id, partner_id, ship_to_id,
                request_type, lead_id, lead_company, lead_name,
                context=context,
                )
        res['value']['phone'] = self._get_phone(
                cr, uid,
                (('res.partner', contact_id), ('crm.lead', lead_id), ('res.partner', partner_id)),
                context=context,
                )
        return res

    def onchange_request_type(
            self, cr, uid, ids,
            user_id, contact_id, partner_id, ship_to_id,
            request_type, lead_id, lead_company, lead_name,
            context=None,
            ):
        res = {'value': {}}
        if request_type == 'customer':
            lead_id = res['value']['lead_id'] = False
            lead_company = res['value']['lead_company'] = False
            lead_name = res['value']['lead_name'] = False
        elif request_type == 'lead':
            contact_id = res['value']['contact_id'] = False
            partner_id = res['value']['partner_id'] = False
        else:
            raise ERPError('unknown request type: %r' % (request_type, ))
        res['value']['address'] = self._get_address(
                cr, uid,
                user_id, contact_id, partner_id, ship_to_id,
                request_type, lead_id, lead_company, lead_name,
                context=context,
                )
        return res

    def onchange_ship_to_id(
            self, cr, uid, ids,
            user_id, contact_id, partner_id, ship_to_id,
            request_type, lead_id, lead_company, lead_name,
            context=None,
            ):
        res = {'value': {}, 'domain': {}}
        res['value']['address'] = self._get_address(
                cr, uid,
                user_id, contact_id, partner_id, ship_to_id,
                request_type, lead_id, lead_company, lead_name,
                context=context,
                )
        return res

    def onload(self, cr, uid, ids, user_id, contact_id, partner_id, ship_to_id, request_type, lead_id, lead_company, lead_name, context=None):
        # if request type is customer, set domains for partner related fields
        res = {}
        if request_type == 'customer':
            res = self.onchange_partner_id(
                    cr, uid, ids,
                    user_id, contact_id, partner_id, ship_to_id,
                    request_type, lead_id, lead_company, lead_name,
                    context=context,
                    )
            if 'value' in res:
                del res['value']
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
            complete = False
            if isinstance(ids, (int, long)):
                ids = [ids]
            user = self.pool.get('res.users').browse(cr, uid, uid, context=context)
            for record in self.browse(cr, SUPERUSER_ID, ids, context=context):
                vals = values.copy()
                proposed = Proposed(self, cr, values, record, context=context)
                if 'state' in vals:
                    old_state = record.state
                    new_state = vals['state']
                    if record.state == 'draft' and new_state not in ('draft', ):
                        # make sure 'submit' happens before other, later, states
                        self.button_sample_submit(cr, uid, ids, context=context)
                    if 'product_ids' in vals and old_state != 'draft':
                        if not user.has_group('sample.group_sample_user'):
                            raise ERPError('Error', 'Order has already been submitted.  Talk to someone in Samples to get more products added.')
                if proposed.state != 'draft' and not proposed.product_ids:
                    raise ERPError('Missing Products', 'Sample request has no products listed!')
                elif record.state != 'complete' and proposed.state == 'complete':
                    complete = True
                    vals.pop('state')
                super(sample_request, self).write(cr, uid, [record.id], vals, context=context)
                if complete:
                    self.button_complete(cr, uid, [record.id], context=context)
            return True
        return super(sample_request, self).write(cr, uid, ids, values, context=context)


class sample_product(osv.Model):

    _name = 'sample.product'

    _columns = {
        'name': fields.related('product_id', 'name', type='char', size=128),
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
