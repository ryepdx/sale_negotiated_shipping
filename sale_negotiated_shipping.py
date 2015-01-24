    # -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2015 RyePDX LLC
#    Copyright (C) 2011 NovaPoint Group LLC (<http://www.novapointgroup.com>)
#    Copyright (C) 2004-2010 OpenERP SA (<http://www.openerp.com>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>
#
##############################################################################

import logging
from collections import namedtuple

from openerp.osv import fields, osv
from openerp.tools.translate import _

ManualShippingRate = namedtuple("ManualShippingRate", ["charge", "percentage"])

class shipping_rate_card(osv.osv):
    _name = 'shipping.rate.card'
    _description = "Ground Shipping Calculation Table"
    _columns = {
        'name': fields.char('Name', size=128, required=True),
        'from_date': fields.datetime('From Date'),
        'to_date': fields.datetime('To Date'),
        'rate_ids': fields.one2many('shipping.rate', 'card_id', 'Shipping Rates', required=True),
    }

shipping_rate_card()

class shipping_rate_config(osv.osv):
    _name = 'shipping.rate.config'
    _description = "Configuration for shipping rate"
    _rec_name = 'name'

    _columns = {
        'name': fields.char('Name', size=128, help='Shipping method name. Displayed in the wizard.'),
        'active': fields.boolean('Active', help='Indicates whether a shipping method is active'),
        'calc_method': fields.selection([
            ('country_price', 'Country & Order Total'),
            ('manual', 'Manually Calculate')
            ], 'Shipping Calculation Method', help='Shipping method name. Displayed in the wizard.'),
        'shipping_wizard': fields.integer('Shipping Wizard'),
        'account_id': fields.many2one('account.account', 'Account', help='This account represents the g/l account for booking shipping income.'),
        'shipment_tax_ids': fields.many2many('account.tax', 'shipment_tax_rel', 'shipment_id', 'tax_id', 'Taxes', domain=[('parent_id', '=', False)]),
        'rate_card_id': fields.many2one('shipping.rate.card', 'Shipping Rate Card', required=True)
    }
    
    _defaults = {
        'calc_method': 'country_price',
        'active': True
    }

shipping_rate_config()


class shipping_rate(osv.osv):
    _name = 'shipping.rate'
    _description = "Shipping Calculation Table"
    _columns = {
        'name': fields.related('card_id', 'name', type='char', string="Name", store=True),
        'from_price': fields.float('From Price', required=True),
        'to_price': fields.float('To Price', required=False),
        'physical_only': fields.boolean('Only count physical products toward to and from prices'),
        'charge': fields.float('Flate Rate', required=True),
        'percentage': fields.float('Percentage Rate', required=True),
        'country_id': fields.many2one('res.country', 'Country'),
        'card_id': fields.many2one('shipping.rate.card', 'Shipping Table')
    }
    _defaults = {
        'from_price': 0.0,
        'charge': 0,
        'percentage': 0,
    }

    def find_cost(self, cr, uid, config_id, address, model_obj, context=None):
        """
        Function to calculate shipping cost
        """
        config_pool = self.pool.get('shipping.rate.config')
        config_obj = config_pool.browse(cr, uid, config_id, context=context)

        if config_obj.calc_method == 'country_price':
            table_pool = self.pool.get('shipping.rate')
            table_ids = table_pool.search(cr, uid, [
                ('card_id', '=', config_obj.rate_card_id.id),
                '|', ('country_id', '=', address.country_id.id), ('country_id', '=', None),
                '|',
                '&', '&', '|', '|', ('to_price', '>=', model_obj.amount_total), ('to_price', '=', 0.0), ('to_price', '=', None),
                      ('from_price', '<=', model_obj.amount_total), ('physical_only', '=', False),
                '&', '&', '|', '|', ('to_price', '>=', model_obj.amount_physical), ('to_price', '=', 0.0),
                      ('to_price', '=', None),
                      ('from_price', '<=', model_obj.amount_physical), ('physical_only', '=', True)
            ], order=['country_id', 'to_price'], context=context)

            if table_ids:
                return table_pool.browse(cr, uid, table_ids[0], context=context)

            logger = logging.getLogger(__name__)
            logger.warning(_("Unable to find rate table with Shipping Table = %s and Country = %s." % (
                config_obj.rate_card_id.name, address.country_id.name
            )))

        return ManualShippingRate(charge=0.0, percentage=0.0)

shipping_rate()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
