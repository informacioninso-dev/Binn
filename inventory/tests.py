from decimal import Decimal

from django.test import SimpleTestCase

from .models import InventoryItem, StockMovement, StockMovementType


class StockMovementTests(SimpleTestCase):
    def test_signed_quantity_is_negative_for_outbound(self):
        item = InventoryItem(sku="INS-001", name="Guantes")
        movement = StockMovement(
            item=item,
            movement_type=StockMovementType.OUTBOUND,
            quantity=Decimal("3.00"),
        )

        self.assertEqual(movement.signed_quantity, Decimal("-3.00"))
