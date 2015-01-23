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

import datetime
from decimal import Decimal

import decimal_precision as dp
from openerp.osv import fields, osv

class sale_order(osv.osv):
    _inherit = "sale.order"

    def _amount_all(self, cr, uid, ids, field_name, arg, context=None):
        cur_obj = self.pool.get('res.currency')
        res = {}
        for order in self.browse(cr, uid, ids, context=context):
            res[order.id] = {
                'amount_untaxed': 0.0,
                'amount_tax': 0.0,
                'amount_total': 0.0,
            }

            tax = subtotal = 0.0
            cur = order.pricelist_id.currency_id
            for line in order.order_line:
                subtotal += line.price_subtotal
                tax += self._amount_line_tax(cr, uid, line, context=context)

            res[order.id]['amount_tax'] = cur_obj.round(cr, uid, cur, tax)
            res[order.id]['amount_untaxed'] = cur_obj.round(cr, uid, cur, subtotal)
            res[order.id]['amount_total'] = (res[order.id]['amount_untaxed'] + res[order.id]['amount_tax']
                + res[order.id]['shipcharge'] + cur_obj.round(cr, uid, cur, context.get("shipcharge", order.shipcharge))
            )

        return res

    def _get_order(self, cr, uid, ids, context=None):
        result = {}
        for line in self.pool.get('sale.order.line').browse(cr, uid, ids, context=None):
            result[line.order_id.id] = True
        return result.keys()

    def _make_invoice(self, cr, uid, order, lines, context=None):
        inv_id = super(sale_order, self)._make_invoice(cr, uid, order, lines, context=None)
        if inv_id:
            if order.sale_account_id:
                inv_obj = self.pool.get('account.invoice')
                inv_obj.write(cr, uid, inv_id, {
                    'shipcharge': order.shipcharge,
                    'ship_method_id': order.ship_method_id.id,
                    'sale_account_id': order.sale_account_id.id,
                    })
                inv_obj.button_reset_taxes(cr, uid, [inv_id], context=context)
        return inv_id

    def _amount_shipment_tax(self, cr, uid, shipment_taxes, shipment_charge):
        val = 0.0
        for c in self.pool.get('account.tax').compute_all(cr, uid, shipment_taxes, shipment_charge, 1)['taxes']:
            val += c.get('amount', 0.0)
        return val

    def _amount_all(self, cr, uid, ids, field_name, arg, context=None):
        cur_pool = self.pool.get('res.currency')
        res = dict([(sale.id, {'amount_physical': cur_pool.round(cr, uid, sale.pricelist_id.currency_id, sum(
                [line.price_subtotal for line in sale.order_line if line.product_id.type != "service"]
            ))}) for sale in self.browse(cr, uid, ids, context=context)])

        if field_name == 'amount_physical':
            return res

        res2 = super(sale_order, self)._amount_all(cr, uid, ids, field_name, arg, context=context)
        for sale_id in ids:
            res[sale_id] = dict(res.get(sale_id, {}).items() + res2.get(sale_id, {}).items())

        for order in self.browse(cr, uid, ids, context=context):
            cur = order.pricelist_id.currency_id
            tax_ids = order.ship_method_id and "shipment_tax_ids" in order.ship_method_id._columns \
                      and order.ship_method_id.shipment_tax_ids

            if tax_ids:
                val = self._amount_shipment_tax(cr, uid, tax_ids, order.shipcharge)
                res[order.id]['amount_tax'] += cur_pool.round(cr, uid, cur, val)

            ship_methods = None
            if not order.ship_method_id:
                ship_methods = self._get_ship_methods(
                    cr, uid, order.recipient_country_id.id,
                    res[order.id]['amount_untaxed'], res[order.id]['amount_physical']
                )

            if ship_methods:
                order.shipcharge = self._get_ship_charge(cr, uid, ship_methods[0], order.id, context=context)
                self.write(
                    cr, uid, order.id, {
                        "shipcharge": order.shipcharge,
                        "ship_method_id": ship_methods[0].id
                    }, context=context
                )

            res[order.id]['amount_total'] = res[order.id]['amount_untaxed'] + res[order.id]['amount_tax'] + order.shipcharge

        return res

    def _get_sale_ship_methods(self, cr, uid, ids, field_name, args, context=None):
        methods = {}
        todays_ratecards = self._get_todays_ratecards(cr, uid, context=context)

        for sale_obj in self.browse(cr, uid, ids):
            methods[sale_obj.id] = [m.id for m in self._get_ship_methods(
                cr, uid, sale_obj.recipient_country_id.id, sale_obj.amount_total, sale_obj.amount_physical,
                ratecards=todays_ratecards, context=context
            )]

        return methods

    def _get_todays_ratecards(self, cr, uid, context=None):
        table_pool = self.pool.get('shipping.rate.card')
        today = datetime.date.today().strftime("%Y-%m-%d")

        return table_pool.browse(cr, uid, table_pool.search(
            cr, uid, ['|', ('from_date', '<=', today), ('from_date', '=', None),
                      '|', ('to_date', '>', today), ('to_date', '=', None)], context=context
        ), context=context)

    def _get_ship_methods(self, cr, uid, country_id, amount_total, physical_total, ratecards=None, context=None):
        rate_pool = self.pool.get('shipping.rate')

        if ratecards is None:
            ratecards = self._get_todays_ratecards(cr, uid, context=context)

        method_objs = rate_pool.browse(cr, uid, rate_pool.search(cr, uid, [
            '|', ('country_id', '=', country_id), ('country_id', '=', None),
            '|', '|', ('to_price', '>=', amount_total), ('to_price', '=', 0.0), ('to_price', '=', None),
                      ('from_price', '<=', amount_total),
            '|', '|', ('to_price_physical', '>=', physical_total), ('to_price_physical', '=', 0.0),
                      ('to_price_physical', '=', None),
                      ('from_price_physical', '<=', physical_total),
            '|', ('id', 'in', [r.id for t in ratecards for r in t.rate_ids]), ('card_id', '=', None)
        ], order='country_id, charge, to_price_physical, to_price', context=context), context=context)

        methods = []
        seen_methods = []

        for method in method_objs:
            if method.name not in seen_methods:
                methods.append(method)
                seen_methods.append(method.name)

        return methods

    _columns = {
        'shipcharge': fields.float('Shipping Cost', required=True),
        'ship_method_id': fields.many2one('shipping.rate', 'Shipping Method',
                                          domain="[('id', 'in', valid_shipping_methods[0][2])]",
                                          context="{'group_by':'name', 'order':'country_id, to_price'}"
        ),
        'valid_shipping_methods': fields.function(_get_sale_ship_methods, type="many2many", relation="shipping.rate"),
        'recipient_country_id': fields.related(
            "partner_shipping_id", "country_id", type="many2one", relation="res.country", store=False
        ),
        'sale_account_id': fields.many2one('account.account', 'Shipping Account',
                                           help='This account represents the g/l account for booking shipping income.'),
        'amount_untaxed': fields.function(_amount_all, method=True, digits_compute= dp.get_precision('Sale Price'), string='Untaxed Amount',
            store = {
               'sale.order': (lambda self, cr, uid, ids, c={}: ids, ['order_line', 'ship_method_id', 'shipcharge'], 10),
               'sale.order.line': (_get_order, ['price_unit', 'tax_id', 'discount', 'product_uom_qty'], 10),
               },
               multi='sums', help="The amount without tax."),
        'amount_tax': fields.function(_amount_all, method=True, digits_compute=dp.get_precision('Sale Price'), string='Taxes',
            store = {
                'sale.order': (lambda self, cr, uid, ids, c={}: ids, ['order_line', 'ship_method_id', 'shipcharge'], 10),
                'sale.order.line': (_get_order, ['price_unit', 'tax_id', 'discount', 'product_uom_qty'], 10),
                },
                multi='sums', help="The tax amount."),
        'amount_physical': fields.function(_amount_all, method=True, digits_compute= dp.get_precision('Sale Price'), string='Total',
            store = {
                'sale.order': (lambda self, cr, uid, ids, c={}: ids, ['order_line', 'ship_method_id', 'shipcharge'], 10),
                'sale.order.line': (_get_order, ['price_unit', 'tax_id', 'discount', 'product_uom_qty'], 10),
                },
                multi='sums', help="The total amount."),
        'amount_total': fields.function(_amount_all, method=True, digits_compute= dp.get_precision('Sale Price'), string='Total',
            store = {
                'sale.order': (lambda self, cr, uid, ids, c={}: ids, ['order_line', 'ship_method_id', 'shipcharge'], 10),
                'sale.order.line': (_get_order, ['price_unit', 'tax_id', 'discount', 'product_uom_qty'], 10),
                },
                multi='sums', help="The total amount.")
    }

    def onchange_partner_id(self, cr, uid, ids, partner_id, context=None):
        res = super(sale_order, self).onchange_partner_id(cr, uid, ids, partner_id, context=context) or {}

        if "value" not in res:
            res["value"] = {}

        sale_total = 0.0
        physical_total = 0.0

        if ids:
            sale = self.browse(cr, uid, ids[0], context=context)
            sale_total = sale.amount_untaxed
            physical_total = sale.amount_physical

        partner = self.pool.get("res.partner").browse(cr, uid, partner_id, context=context)
        methods = self._get_ship_methods(cr, uid, partner.country_id.id, sale_total, physical_total)

        if not methods:
            return res

        res["value"]["valid_shipping_methods"] = [m.id for m in methods]

        selected_ship_method = methods[0].id
        international = partner.country_id.name not in ['United States', 'Canada']

        for method in methods:
            if (not international and method.name.lower() == 'pw shipping') \
                    or (international and method.name.lower() == 'pw int shipping'):
                selected_ship_method = method.id

        res["value"]["ship_method_id"] = selected_ship_method

        return res

    def onchange_ship_method(self, cr, uid, ids, ship_method_id, context=None):
        if not ids or not ship_method_id:
            return {"value": {"shipcharge": 0.0}}

        rate_pool = self.pool.get("shipping.rate")
        method = rate_pool.browse(cr, uid, ship_method_id, context=context)

        return {"value": {"shipcharge": self._get_ship_charge(cr, uid, method, ids[0], context=context)}}

    def onchange_update_total(self, cr, uid, ids, shipcharge, amount_untaxed, amount_tax):
        return {"value": {"amount_total": shipcharge + amount_untaxed + amount_tax}}

    def _get_ship_charge(self, cr, uid, method, order_id, context=None):
        shipcharge = method.charge if method and method.charge else 0.0

        if method and method.percentage:
            order = self.browse(cr, uid, order_id, context=context)
            shipcharge += float(Decimal(
                Decimal(order.amount_untaxed) * (Decimal(method.percentage) / Decimal(100))
            ).quantize(Decimal("1.00")))

        return shipcharge

sale_order()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
