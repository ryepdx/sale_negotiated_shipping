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

import time
import decimal_precision as dp

from openerp.osv import osv, fields

class account_invoice(osv.osv):
    _inherit = "account.invoice"

    def _total_weight_net(self, cr, uid, ids, field_name, arg, context=None):
        """Compute the total net weight of the given Invoice."""
        result = {}
        for invoice in self.browse(cr, uid, ids, context=context):
            result[invoice.id] = 0.0
            for line in invoice.invoice_line:
                if line.product_id:
                    result[invoice.id] += line.weight_net or 0.0
        return result

    def _get_invoice(self, cr, uid, ids, context=None):
        """Get the invoice ids of the given Invoice Lines."""
        result = {}
        for line in self.pool.get('account.invoice.line').browse(cr, uid, ids, context=context):
            result[line.invoice_id.id] = True
        return result.keys()

    def _amount_shipment_tax(self, cr, uid, shipment_taxes, shipment_charge):
        val = 0.0
        for c in self.pool.get('account.tax').compute_all(cr, uid, shipment_taxes, shipment_charge, 1)['taxes']:
            val += c.get('amount', 0.0)
        return val

    def _get_invoice_tax(self, cr, uid, ids, context=None):
        invoice = self.pool.get('account.invoice')
        return super(account_invoice, invoice)._get_invoice_tax(cr, uid, ids, context=context)

    def _get_invoice_line(self, cr, uid, ids, context=None):
        invoice = self.pool.get('account.invoice')
        return super(account_invoice, invoice)._get_invoice_line(cr, uid, ids, context=context)

    def _get_invoice_from_line(self, cr, uid, ids, context=None):
        invoice = self.pool.get('account.invoice')
        return super(account_invoice, invoice)._get_invoice_from_line(cr, uid, ids, context=context)

    def finalize_invoice_move_lines(self, cr, uid, invoice, move_lines):
        """
        finalize_invoice_move_lines(cr, uid, invoice, move_lines) -> move_lines
        Hook method to be overridden in additional modules to verify and possibly alter the
        move lines to be created by an invoice, for special cases.
        Args:
            invoice: browsable record of the invoice that is generating the move lines
            move_lines: list of dictionaries with the account.move.lines (as for create())
        Returns:
            The (possibly updated) final move_lines to create for this invoice
        """
        move_lines = super(account_invoice, self).finalize_invoice_move_lines(cr, uid, invoice, move_lines)
        if invoice.type == "out_refund":
            account = invoice.account_id.id
        else:
            account = invoice.sale_account_id.id
        if invoice.type in ('out_invoice','out_refund')  and account and invoice.shipcharge:
            lines1 = {
                'analytic_account_id': False,
                'tax_code_id': False,
                'analytic_lines': [],
                'tax_amount': False,
                'name': 'Shipping Charge',
                'ref': '',
                'currency_id': False,
                'credit': invoice.shipcharge,
                'product_id': False,
                'date_maturity': False,
                'debit': False,
                'date': time.strftime("%Y-%m-%d"),
                'amount_currency': 0,
                'product_uom_id':  False,
                'quantity': 1,
                'partner_id': invoice.partner_id.id,
                'account_id': account
            }
            move_lines.append((0, 0, lines1))
            has_entry = False
            for move_line in move_lines:
                journal_entry = move_line[2]
                if journal_entry['account_id'] == invoice.partner_id.property_account_receivable.id:
                    journal_entry['debit'] += invoice.shipcharge
                    has_entry = True
                    break
            if not has_entry:       # If debit line does not exist create one
                lines2 = {
                    'analytic_account_id': False,
                    'tax_code_id': False,
                    'analytic_lines': [],
                    'tax_amount': False,
                    'name': '/',
                    'ref': '',
                    'currency_id': False,
                    'credit': False,
                    'product_id': False,
                    'date_maturity': False,
                    'debit': invoice.shipcharge,
                    'date': time.strftime("%Y-%m-%d"),
                    'amount_currency': 0,
                    'product_uom_id': False,
                    'quantity': 1,
                    'partner_id': invoice.partner_id.id,
                    'account_id': invoice.partner_id.property_account_receivable.id
                }
                move_lines.append((0, 0, lines2))
        return move_lines

    def _amount_all(self, cr, uid, ids, field_name, arg, context=None):
        cur_pool = self.pool.get('res.currency')
        res = dict([(invoice.id, {'amount_physical': cur_pool.round(cr, uid, invoice.currency_id, sum(
                [line.price_subtotal for line in invoice.move_lines if line.product_id.type != "service"]
            ))}) for invoice in self.browse(cr, uid, ids, context=context)])

        if field_name == 'amount_physical':
            return res

        res2 = super(account_invoice, self)._amount_all(cr, uid, ids, field_name, arg, context=context)

        for invoice_id in ids:
            res[invoice_id] = dict(res.get(invoice_id, {}).items() + res2.get(invoice_id, {}).items())

        for invoice in self.browse(cr, uid, ids, context=context):
            res[invoice.id]['amount_total'] = (
                res[invoice.id]['amount_untaxed'] + res[invoice.id]['amount_tax'] + invoice.shipcharge
            )

        return res

    def _get_invoice_ship_methods(self, cr, uid, ids, field_name, args, context=None):
        methods = {}
        todays_ratecards = self._get_todays_ratecards(cr, uid, context=context)
        sale_pool = self.pool.get("sale.order")

        for invoice_obj in self.browse(cr, uid, ids):
            methods[invoice_obj.id] = [m.id for m in sale_pool._get_ship_methods(
                cr, uid, invoice_obj.recipient_country_id.id, invoice_obj.amount_total,
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

    _columns = {
        'shipcharge': fields.float('Shipping Cost', required=True),
        'ship_method_id': fields.many2one('shipping.rate', 'Shipping Method',
                                          domain="[('id', 'in', valid_shipping_methods[0][2])]",
                                          context="{'group_by':'name', 'order':'country_id, to_price'}"
        ),
        'valid_shipping_methods': fields.function(_get_invoice_ship_methods, type="many2many", relation="shipping.rate"),
        'recipient_country_id': fields.related(
            "partner_id", "country_id", type="many2one", relation="res.country", store=False
        ),
        'sale_account_id': fields.many2one('account.account', 'Shipping Account',
                                           help='This account represents the g/l account for booking shipping income.'),
        'amount_untaxed': fields.function(_amount_all, method=True, digits_compute= dp.get_precision('Sale Price'), string='Untaxed Amount',
            store = {
                'account.invoice': (lambda self, cr, uid, ids, c={}: ids, ['invoice_line','shipcharge'], -10),
                'account.invoice.tax': (_get_invoice_tax, None, -10),
                'account.invoice.line': (_get_invoice_line, ['price_unit', 'invoice_line_tax_id', 'quantity', 'discount', 'invoice_id'], -10),
                }, multi='sums', help="The amount without tax."),
        'amount_tax': fields.function(_amount_all, method=True, digits_compute=dp.get_precision('Sale Price'), string='Tax',
            store = {
                'account.invoice': (lambda self, cr, uid, ids, c={}: ids, ['invoice_line','shipcharge'], -10),
                'account.invoice.tax': (_get_invoice_tax, None, -10),
                'account.invoice.line': (_get_invoice_line, ['price_unit', 'invoice_line_tax_id', 'quantity', 'discount', 'invoice_id'], -10),
                }, multi='sums', help="The tax amount."),
        'amount_physical': fields.function(_amount_all, method=True, digits_compute= dp.get_precision('Sale Price'), string='Total',
            store = {
                'account.invoice': (lambda self, cr, uid, ids, c={}: ids, ['invoice_line','shipcharge'], -10),
                'account.invoice.tax': (_get_invoice_tax, None, -10),
                'account.invoice.line': (_get_invoice_line, ['price_unit', 'invoice_line_tax_id', 'quantity', 'discount', 'invoice_id'], -10),
                },
                multi='sums', help="The total physical amount."),
        'amount_total': fields.function(_amount_all, method=True, digits_compute=dp.get_precision('Account'), string='Total',
            store = {
                'account.invoice': (lambda self, cr, uid, ids, c={}: ids, ['invoice_line','shipcharge'], -10),
                'account.invoice.tax': (_get_invoice_tax, None, -10),
                'account.invoice.line': (_get_invoice_line, ['price_unit', 'invoice_line_tax_id', 'quantity', 'discount', 'invoice_id'], -10),
                }, multi='sums'),
        'total_weight_net': fields.function(_total_weight_net, method=True, string='Total Net Weight',
            store = {
                'account.invoice': (lambda self, cr, uid, ids, c={}: ids, ['invoice_line'], 10),
                'account.invoice.line': (_get_invoice, ['quantity', 'product_id'], 10),
                },help="The cumulated net weight of all the invoice lines."),
    }
    defaults = {
        "shipcharge": 0.0
    }

    def onchange_update_total(self, cr, uid, ids, shipcharge, amount_untaxed, amount_tax):
        return {"value": {"amount_total": shipcharge + amount_untaxed + amount_tax}}

account_invoice()

class invoice_line(osv.osv):
    """Add the net weight to the object "Invoice Line"."""
    _inherit = 'account.invoice.line'

    def _weight_net(self, cr, uid, ids, field_name, arg, context=None):
        """Compute the net weight of the given Invoice Lines."""
        result = {}
        for line in self.browse(cr, uid, ids, context=context):
            result[line.id] = 0.0
            if line.product_id:
                result[line.id] += line.product_id.weight_net * line.quantity
        return result
    
    
    _columns = {
        'weight_net': fields.function(_weight_net, method=True, string='Net Weight', help="The net weight in Kg.",
            store = {
                'account.invoice.line': (lambda self, cr, uid, ids, c={}: ids,['quantity', 'product_id'], -11),
                })
    }

invoice_line()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
