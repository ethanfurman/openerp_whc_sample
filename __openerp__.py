# -*- coding: utf-8 -*-

{
    'name': 'Samples',
    'version': '0.1',
    'category': 'Generic Modules',
    'sequence': 33,
    'summary': 'Order and track product samples.',
    'description': 'Order and track product samples to existing and potential customers.',
    'author': 'Van Sebille Systems',
    'depends': [
        'base',
        'crm',
        'fnx',
        'product',
        'web',
        ],
    'update_xml': [
        'security/sample_security.xaml',
        'security/ir.model.access.csv',
        'sample_view.xaml',
        'sample_data.xaml',
        'res_config_view.xaml',
        'res_partner_view.xaml',
        'wizard/wizard_defaults_view.xaml',
        ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
