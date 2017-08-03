# -*- coding: utf-8 -*-

import openerp
from openerp import SUPERUSER_ID
from openerp.addons.web import http
from openerp.addons.web.controllers.main import content_disposition
import logging
from mimetypes import guess_type
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from StringIO import StringIO
from antipathy import Path
from openerp.addons.fnx import Humanize

_logger = logging.getLogger(__name__)
style_sheet = getSampleStyleSheet()

class SampleRequest(http.Controller):

    _cp_path = '/samplerequest'

    def __getattr__(self, name):
        return self.get_file

    @http.httprequest
    def get_file(self, request):
        target_file = Path(request.httprequest.path)
        target_company = target_file.path.filename
        target_id = int(target_file.filename[14:-4])
        registry = openerp.modules.registry.RegistryManager.get(target_company)
        with registry.cursor() as cr:
            order = registry.get('sample.request').browse(cr, SUPERUSER_ID, target_id)
            file_data = self.create_pdf(Humanize(order, request.context), order.state=='complete')
            return request.make_response(
                    file_data,
                    headers=[
                        ('Content-Disposition',  content_disposition(target_file.filename, request)),
                        ('Content-Type', guess_type(target_file.filename)[0] or 'octet-stream'),
                        ('Content-Length', len(file_data)),
                        ],
                    )


    def create_pdf(self, order, complete):
        # get data
        sales_left = self.get_sales_left(order)
        sales_right = self.get_sales_right(order)
        sample_only = self.get_sample_only(order)
        first_section = self.get_first_section(order)
        items = self.get_items(order)
        second_section = self.get_second_section(order)
        shipping_left = self.get_shipping_left(order)
        shipping_right = self.get_shipping_right(order)
        # style it
        sections = []
        # title
        sections.append(Table(
            [[
                Paragraph('SunRidge Farms Samples Request', style_sheet['h1']),
                Paragraph(order.rush, style_sheet['h1']),
                ]],
            colWidths=[450, 90],
            rowHeights=None,
            ))
        sections.append(Spacer(540, 18))
        # header 
        table_left = Table(sales_left, colWidths=[108, 150], rowHeights=None, style=lines)
        table_right = Table(sales_right, colWidths=[108, 136], rowHeights=None, style=lines)
        table_top = Table(
                [[table_left, '', table_right]],
                colWidths=[254, 32, 254],
                rowHeights=None,
                style=TableStyle([
                    ('BOX', (0,0), (-1,-1), 1, colors.black),
                    ('TOPPADDING', (0,0), (-1,-1), 0),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                    ('LEFTPADDING', (0,0), (-1,-1), 0),
                    ('RIGHTPADDING', (0,0), (-1,-1), 0),
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
                    ]),
                )
        sections.append(table_top)
        table_middle = Table(
                sample_only,
                colWidths=[180]*3,
                rowHeights=[24, 20],
                style=TableStyle([
                    ('BOX', (0,0), (-1,-1), 1, colors.black),
                    ('LINEBELOW', (0,0), (-1,0), 0.25, colors.black),
                    ('SPAN', (0,0), (-1,0)),
                    ('ALIGN', (0,0), (-1,0), 'CENTER'),
                    ('ALIGN', (0,1), (0,1), 'LEFT'),
                    ('ALIGN', (1,1), (1,1), 'CENTER'),
                    ('ALIGN', (2,1), (2,1), 'RIGHT'),
                    ]),
                )
        sections.append(table_middle)
        # first free-floating text
        sections.append(Spacer(540, 18))
        sections.append(
                Table(
                    first_section,
                    colWidths=[125, 415],
                    rowHeights=None,
                    style=TableStyle([
                        ('VALIGN', (0,0), (0,0), 'TOP'),
                        ]),
                ))
        sections.append(Spacer(540, 18))
        # items
        table_bottom = Table(
                items,
                colWidths=[108, 288, 60, 84],
                rowHeights=[20] + [(30, None)[complete]]*(len(items)-1),
                style=TableStyle([
                    ('LINEBELOW', (0,0), (-1,-1), 0.25, colors.black),
                    ('ALIGN', (-1, 0), (-1, -1), 'RIGHT')
                    ]),
                )
        sections.append(table_bottom)
        sections.append(Spacer(540, 18))
        # second free-floating text
        sections.append(
                Table(
                    second_section,
                    colWidths=[125, 415],
                    rowHeights=[30]*2,
                ))
        sections.append(Spacer(540, 18))
        # shipping
        table_shipping_left = Table(
                shipping_left,
                colWidths=[108, 144],
                rowHeights=[30]*4,
                style=lines,
                )
        table_shipping_right = Table(
                shipping_right,
                colWidths=[108, 144],
                rowHeights=[60]*2,
                style=lines,
                )
        table_shipping = Table(
                [[table_shipping_left, '', table_shipping_right]],
                colWidths=[254, 32, 254],
                rowHeights=None,
                style=TableStyle([
                    ('BOX', (0,0), (-1,-1), 1, colors.black),
                    # ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                    ('TOPPADDING', (0,0), (-1,-1), 0),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                    ('LEFTPADDING', (0,0), (-1,-1), 0),
                    ('RIGHTPADDING', (0,0), (-1,-1), 0),
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
                    ]),
                )
        sections.append(table_shipping)
        stream = StringIO()
        SimpleDocTemplate(stream, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36, title='Sample Request').build(sections)
        return stream.getvalue()

    def get_sales_left(self, order):
        return [
                ['Department', order.department],
                ['Request by', order.user_id.name],
                ['Created on', order.create_date],
                ['Samples Must',  ('%s on %s  %s' % (order.target_date_type, order.target_date, order.ship_early)).strip()],
                ['Send to', order.send_to],
                ['Recipient', '\n'.join([t for t in (order.contact_name, order.partner_id.name) if t])],
                ]

    def get_sales_right(self, order):
        return [
                ['Ship via', order.request_ship],
                ['Address Type', order.address_type],
                ['Shipping Label', order.address],
                ['Add Ice', order.ice],
                ['3rd Party Account #', order.third_party_account],
                ]

    def get_sample_only(self, order):
        return [
                ['Samples Department Only'],
                [   'Invoice #:  %s' % order.invoice,
                    'Julian Date Code:  %s' % order.julian_date_code,
                    'Production Order #:  %s' % order.production_order,
                    ],
                ]
    def get_first_section(self, order):
        return [
                ['Special Instructions:', Paragraph(order.instructions, style_sheet['BodyText'])],
                ]

    def get_items(self, order):
        items = [['Qty', 'Item', 'Lot # Requested', '/     Used']]
        for item in order.product_ids:
            items.append([
                item.qty_id.name,
                item.product_id.name_get,
                item.product_lot_requested,
                (item.product_lot_used, '✓')[bool(item.product_lot_used) and item.product_lot_requested==item.product_lot_used],
                ])
        return items

    def get_second_section(self, order):
        return [
                ['Preparation Time:', order.prep_time or ''],
                ['Finished on:', order.finish_date],
                ]

    def get_shipping_left(self, order):
        return [
                ['Shipping Method:', order.actual_ship],
                ['Shipping Cost:', order.shipping_cost or ''],
                ['Shipped on:', order.actual_ship_date],
                ['Tracking #:', order.tracking],
                ]

    def get_shipping_right(self, order):
        return [
                ['Received by:', order.received_by],
                ['Received on:', order.received_datetime],
                ]


lines = TableStyle([
    ('LINEBELOW', (0,0), (-1,-1), 0.25, colors.black),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ])

