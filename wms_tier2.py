"""
Warehouse Management System - Tier 2
Metropolia University of Applied Sciences
Student: Jakob Balloch

Description:
    Tracks items in batches (FIFO - First In First Out).
    Each delivery is recorded as a separate batch with a timestamp.
    When dispatching, the oldest batch is always used first.

How to run:
    1. Start the simulator: python -m block_storage_simulator --mode both
    2. Run this file:       python wms_tier2.py
"""

import tkinter as tk
from tkinter import messagebox
import threading
import time
import uuid

from py_ads_client import ADSClient, ADSSymbol, BOOL, INT, LREAL


# ── Connection settings ───────────────────────────────────────────────────────

PLC_IP = "127.0.0.1"
PLC_NET_ID = "127.0.0.1.1.1"
PLC_PORT = 851
LOCAL_NET_ID = "127.0.0.1.1.2"

# ── Machine state codes ───────────────────────────────────────────────────────

STATE_AT_HOME = 101
STATE_AT_IMAGING = 120
STATE_AT_SLOT = 140

# ── Physical measurements (millimetres) ───────────────────────────────────────

BLOCK_SIZE = 60
AREA_WIDTH = 400
AREA_HEIGHT = 300
PALLET_X = 160.0
PALLET_Y = 410.0


# =============================================================================
# CLASS: Batch
# Represents one delivery of a product
# =============================================================================

class Batch:
    """
    One received delivery of a product.
    Records how many units came in and when they arrived.
    """

    def __init__(self, product_name, quantity):
        self.product_name = product_name
        self.quantity = quantity
        self.received_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # Short unique ID for this batch e.g. "A1B2C3D4"
        self.batch_id = str(uuid.uuid4())[:8].upper()

    def __str__(self):
        return f"  Batch {self.batch_id}  qty={self.quantity}  received={self.received_at}"


# =============================================================================
# CLASS: StorageSlot
# Represents one physical position in the storage grid
# =============================================================================

class StorageSlot:
    """One grid position where a block can be stored."""

    def __init__(self, column, row, x, y):
        self.column = column
        self.row = row
        self.x = x
        self.y = y
        self.product = None

    def is_empty(self):
        return self.product is None

    def label(self):
        return f"C{self.column}R{self.row}"


# =============================================================================
# CLASS: StorageGrid
# Manages all the physical storage slots
# =============================================================================

class StorageGrid:
    """
    Divides the storage area into a grid of slots.
    400mm wide / 60mm = 6 columns
    300mm tall  / 60mm = 5 rows  →  30 slots total
    """

    def __init__(self):
        self.slots = []
        half = BLOCK_SIZE / 2

        columns = AREA_WIDTH // BLOCK_SIZE
        rows = AREA_HEIGHT // BLOCK_SIZE

        for col in range(columns):
            for row in range(rows):
                x = half + col * BLOCK_SIZE
                y = half + row * BLOCK_SIZE
                self.slots.append(StorageSlot(col, row, x, y))

    def get_next_free_slot(self):
        """Return the first empty slot, or None if storage is full."""
        for slot in self.slots:
            if slot.is_empty():
                return slot
        return None

    def find_slot_with_product(self, product_name):
        """Find a slot that contains the given product."""
        for slot in self.slots:
            if slot.product == product_name:
                return slot
        return None


# =============================================================================
# CLASS: Warehouse
# Tracks products using FIFO batch queues (Tier 2)
# =============================================================================

class Warehouse:
    """
    Tracks stock using FIFO batches.

    Each product has a list of batches.
    The list is ordered oldest first.
    When dispatching, we always take from the oldest batch first.

    Example:
        Receive 3x Widget-A  →  Batch A (qty=3)
        Receive 2x Widget-A  →  Batch B (qty=2)
        Dispatch 1x Widget-A →  taken from Batch A (oldest)
        Batch A now has qty=2, Batch B still has qty=2
    """

    def __init__(self):
        # Dictionary: product name → list of Batch objects (oldest first)
        self.batches = {}
        self.event_log = []

    def add_item(self, product_name):
        """
        Receive one unit of a product.
        Creates a new batch with quantity 1.
        """
        if product_name not in self.batches:
            self.batches[product_name] = []

        # Each received block gets its own batch record
        new_batch = Batch(product_name, 1)
        self.batches[product_name].append(new_batch)

        total = self.get_total(product_name)
        message = f"IN:  {product_name}  batch={new_batch.batch_id}  (total: {total})"
        self._log(message)
        return message

    def remove_item(self, product_name):
        """
        Dispatch one unit of a product.
        Always takes from the oldest batch first (FIFO).
        """
        if product_name not in self.batches:
            raise ValueError(f"Product '{product_name}' not found.")

        if self.get_total(product_name) == 0:
            raise ValueError(f"No stock for '{product_name}'.")

        # Find the oldest batch that still has stock
        oldest_batch = None
        for batch in self.batches[product_name]:
            if batch.quantity > 0:
                oldest_batch = batch
                break

        if oldest_batch is None:
            raise ValueError(f"No stock for '{product_name}'.")

        # Take one unit from the oldest batch
        oldest_batch.quantity -= 1
        total = self.get_total(product_name)

        message = f"OUT: {product_name}  from batch={oldest_batch.batch_id}  (total: {total})"
        self._log(message)
        return message

    def has_stock(self, product_name):
        """Check if we have at least one unit of a product."""
        return self.get_total(product_name) > 0

    def get_total(self, product_name):
        """Get total units across all batches for a product."""
        if product_name not in self.batches:
            return 0
        return sum(b.quantity for b in self.batches[product_name])

    def get_stock_summary(self):
        """
        Return a list of strings showing current stock with batch details.
        This is what gets displayed in the UI.
        """
        if not self.batches:
            return ["(warehouse is empty)"]

        lines = []
        for product_name, batch_list in self.batches.items():
            total = self.get_total(product_name)

            # Count only batches that still have stock
            active_batches = [b for b in batch_list if b.quantity > 0]

            lines.append(
                f"{product_name}:  {total} unit(s) in {len(active_batches)} batch(es)")

            # Show each active batch
            for batch in active_batches:
                lines.append(
                    f"  Batch {batch.batch_id}  qty={batch.quantity}  received={batch.received_at}")

        return lines

    def _log(self, message):
        """Add a timestamped entry to the event log."""
        timestamp = time.strftime("%H:%M:%S")
        self.event_log.append(f"[{timestamp}]  {message}")


# =============================================================================
# CLASS: MachineConnection
# Handles talking to the simulator over ADS protocol
# =============================================================================

class MachineConnection:
    """
    Sends commands to and reads status from the block storage machine.
    Uses the ADS protocol (industrial standard by Beckhoff).
    """

    def __init__(self):
        self.client = ADSClient(local_ams_net_id=LOCAL_NET_ID)
        self.connected = False

        self.sym_conveyor_state = ADSSymbol(
            "StatusVars.ConveyorState",      INT)
        self.sym_lifter_state = ADSSymbol("StatusVars.LifterState",        INT)
        self.sym_send_pallet = ADSSymbol("Remote.send_pallet",            BOOL)
        self.sym_release_imaging = ADSSymbol(
            "Remote.release_from_imaging",   BOOL)
        self.sym_return_pallet = ADSSymbol(
            "Remote.return_pallet",          BOOL)
        self.sym_transfer_item = ADSSymbol(
            "Remote.transfer_item",          BOOL)
        self.sym_src_x = ADSSymbol("Remote.src_x",                  LREAL)
        self.sym_src_y = ADSSymbol("Remote.src_y",                  LREAL)
        self.sym_dst_x = ADSSymbol("Remote.dst_x",                  LREAL)
        self.sym_dst_y = ADSSymbol("Remote.dst_y",                  LREAL)

    def connect(self):
        """Open connection to the machine."""
        self.client.open(
            target_ip=PLC_IP,
            target_ams_net_id=PLC_NET_ID,
            target_ams_port=PLC_PORT
        )
        self.connected = True

    def disconnect(self):
        """Close the connection."""
        if self.connected:
            self.client.close()
            self.connected = False

    def read_conveyor_state(self):
        return int(self.client.read_symbol(self.sym_conveyor_state))

    def read_lifter_state(self):
        return int(self.client.read_symbol(self.sym_lifter_state))

    def send_pallet(self):
        self.client.write_symbol(self.sym_send_pallet, True)

    def release_from_imaging(self):
        self.client.write_symbol(self.sym_release_imaging, True)

    def return_pallet(self):
        self.client.write_symbol(self.sym_return_pallet, True)

    def transfer_item(self, from_x, from_y, to_x, to_y):
        """Tell the lifter to move a block from one position to another."""
        self.client.write_symbol(self.sym_src_x, float(from_x))
        self.client.write_symbol(self.sym_src_y, float(from_y))
        self.client.write_symbol(self.sym_dst_x, float(to_x))
        self.client.write_symbol(self.sym_dst_y, float(to_y))
        time.sleep(0.05)
        self.client.write_symbol(self.sym_transfer_item, True)

    def wait_for_state(self, target_state, timeout=15):
        """Wait until the conveyor reaches the target state."""
        start = time.time()
        while time.time() - start < timeout:
            current = self.read_conveyor_state()
            if current == target_state:
                return True
            time.sleep(0.2)
        return False


# =============================================================================
# CLASS: WMSController
# Controls the full workflow for receiving and dispatching blocks
# =============================================================================

class WMSController:
    """
    The main controller that ties everything together.
    Same workflow as Tier 1 — the difference is in how
    the Warehouse class records and dispatches stock.
    """

    def __init__(self, on_update):
        self.machine = MachineConnection()
        self.warehouse = Warehouse()
        self.grid = StorageGrid()
        self.on_update = on_update
        self.busy = False

    def connect(self):
        self.machine.connect()
        self.on_update("Connected to simulator.")

    def disconnect(self):
        self.machine.disconnect()

    def receive_block(self, product_name):
        """Run the receive workflow in a background thread."""
        thread = threading.Thread(
            target=self._receive_workflow,
            args=(product_name,)
        )
        thread.daemon = True
        thread.start()

    def dispatch_block(self, product_name):
        """Run the dispatch workflow in a background thread."""
        thread = threading.Thread(
            target=self._dispatch_workflow,
            args=(product_name,)
        )
        thread.daemon = True
        thread.start()

    def _receive_workflow(self, product_name):
        """Full step-by-step workflow to store one block."""
        if self.busy:
            self.on_update("Busy! Wait for current operation to finish.")
            return

        self.busy = True

        try:
            slot = self.grid.get_next_free_slot()
            if slot is None:
                self.on_update("ERROR: Storage is full!")
                return

            self.on_update("Waiting for pallet at home...")
            if not self.machine.wait_for_state(STATE_AT_HOME):
                self.on_update("ERROR: Timed out waiting for home.")
                return

            self.on_update("Sending pallet to imaging...")
            self.machine.send_pallet()
            if not self.machine.wait_for_state(STATE_AT_IMAGING):
                self.on_update("ERROR: Timed out waiting for imaging.")
                return

            self.on_update("Moving to transfer slot...")
            self.machine.release_from_imaging()
            if not self.machine.wait_for_state(STATE_AT_SLOT):
                self.on_update("ERROR: Timed out waiting for transfer slot.")
                return

            self.on_update(
                "Block arrived at transfer slot - lifter preparing...")
            time.sleep(2.0)

            self.on_update(
                f"Lifter moving block to storage slot {slot.label()}...")
            self.machine.transfer_item(PALLET_X, PALLET_Y, slot.x, slot.y)

            self.on_update("Returning pallet home...")
            self.machine.return_pallet()
            if not self.machine.wait_for_state(STATE_AT_HOME):
                self.on_update("ERROR: Timed out returning home.")
                return

            slot.product = product_name
            message = self.warehouse.add_item(product_name)
            self.on_update(f"Done! {message}")

        except Exception as error:
            self.on_update(f"ERROR: {error}")

        finally:
            self.busy = False

    def _dispatch_workflow(self, product_name):
        """Full step-by-step workflow to retrieve one block."""
        if self.busy:
            self.on_update("Busy! Wait for current operation to finish.")
            return

        self.busy = True

        try:
            if not self.warehouse.has_stock(product_name):
                self.on_update(f"ERROR: No stock for '{product_name}'.")
                return

            slot = self.grid.find_slot_with_product(product_name)
            if slot is None:
                self.on_update(
                    f"ERROR: Could not find '{product_name}' in storage.")
                return

            self.on_update("Waiting for pallet at home...")
            if not self.machine.wait_for_state(STATE_AT_HOME):
                self.on_update("ERROR: Timed out waiting for home.")
                return

            self.on_update("Sending pallet to imaging...")
            self.machine.send_pallet()
            if not self.machine.wait_for_state(STATE_AT_IMAGING):
                self.on_update("ERROR: Timed out waiting for imaging.")
                return

            self.on_update("Moving to transfer slot...")
            self.machine.release_from_imaging()
            if not self.machine.wait_for_state(STATE_AT_SLOT):
                self.on_update("ERROR: Timed out waiting for transfer slot.")
                return

            self.on_update(
                f"Lifter retrieving block from slot {slot.label()}...")
            self.machine.transfer_item(slot.x, slot.y, PALLET_X, PALLET_Y)

            self.on_update(
                "Block placed on pallet in transfer slot - returning home...")
            time.sleep(2.0)

            self.on_update("Returning pallet home...")
            self.machine.return_pallet()
            if not self.machine.wait_for_state(STATE_AT_HOME):
                self.on_update("ERROR: Timed out returning home.")
                return

            slot.product = None
            message = self.warehouse.remove_item(product_name)
            self.on_update(f"Done! {message}  —  remove block from pallet.")

        except Exception as error:
            self.on_update(f"ERROR: {error}")

        finally:
            self.busy = False


# =============================================================================
# CLASS: App
# The user interface built with Tkinter
# =============================================================================

class App(tk.Tk):
    """
    The main window for Tier 2.
    Same layout as Tier 1 but the stock panel now shows
    batch details for each product.
    """

    def __init__(self):
        super().__init__()

        self.title("Warehouse Management System - Tier 2")
        self.geometry("700x580")
        self.configure(bg="#1e1e2e")

        self.controller = WMSController(on_update=self.update_status)

        self._build_title()
        self._build_status_and_stock()
        self._build_controls()
        self._build_log()

        thread = threading.Thread(target=self._connect)
        thread.daemon = True
        thread.start()

        self._refresh_display()

    def _build_title(self):
        frame = tk.Frame(self, bg="#1e1e2e")
        frame.pack(fill="x", padx=15, pady=10)

        tk.Label(
            frame,
            text="Warehouse Management System  –  Tier 2",
            font=("Segoe UI", 14, "bold"),
            bg="#1e1e2e",
            fg="#89b4fa"
        ).pack(side="left")

        self.status_label = tk.Label(
            frame,
            text="Connecting...",
            font=("Segoe UI", 10),
            bg="#1e1e2e",
            fg="#f9e2af"
        )
        self.status_label.pack(side="right")

    def _build_status_and_stock(self):
        frame = tk.Frame(self, bg="#1e1e2e")
        frame.pack(fill="both", expand=True, padx=15, pady=5)

        # Left: machine status
        left = tk.LabelFrame(
            frame,
            text="Machine Status",
            font=("Segoe UI", 10, "bold"),
            bg="#2a2a3e",
            fg="#6c7086",
            padx=10, pady=10
        )
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))

        self.conveyor_label = tk.Label(
            left,
            text="Conveyor: —",
            font=("Courier New", 10),
            bg="#2a2a3e",
            fg="#cdd6f4",
            anchor="w"
        )
        self.conveyor_label.pack(fill="x")

        self.lifter_label = tk.Label(
            left,
            text="Lifter: —",
            font=("Courier New", 10),
            bg="#2a2a3e",
            fg="#cdd6f4",
            anchor="w"
        )
        self.lifter_label.pack(fill="x")

        self.wms_label = tk.Label(
            left,
            text="WMS: Ready",
            font=("Courier New", 10),
            bg="#2a2a3e",
            fg="#a6e3a1",
            anchor="w"
        )
        self.wms_label.pack(fill="x")

        # Right: stock with batch info
        right = tk.LabelFrame(
            frame,
            text="Stock  (Tier 2 – FIFO batch tracking)",
            font=("Segoe UI", 10, "bold"),
            bg="#2a2a3e",
            fg="#6c7086",
            padx=10, pady=10
        )
        right.pack(side="right", fill="both", expand=True)

        self.stock_text = tk.Text(
            right,
            font=("Courier New", 10),
            bg="#313145",
            fg="#a6e3a1",
            state="disabled",
            height=8
        )
        self.stock_text.pack(fill="both", expand=True)

    def _build_controls(self):
        frame = tk.LabelFrame(
            self,
            text="Operations",
            font=("Segoe UI", 10, "bold"),
            bg="#1e1e2e",
            fg="#6c7086",
            padx=10, pady=10
        )
        frame.pack(fill="x", padx=15, pady=5)

        tk.Label(
            frame,
            text="Product name:",
            font=("Segoe UI", 10),
            bg="#1e1e2e",
            fg="#cdd6f4"
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.product_entry = tk.Entry(
            frame,
            font=("Segoe UI", 10),
            bg="#313145",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            width=20
        )
        self.product_entry.insert(0, "Widget-A")
        self.product_entry.grid(row=0, column=1, padx=(0, 20))

        self.receive_btn = tk.Button(
            frame,
            text="⬇  RECEIVE (store block)",
            font=("Segoe UI", 10, "bold"),
            bg="#a6e3a1",
            fg="#1e1e2e",
            relief="flat",
            padx=12, pady=6,
            command=self._on_receive
        )
        self.receive_btn.grid(row=0, column=2, padx=(0, 10))

        self.dispatch_btn = tk.Button(
            frame,
            text="⬆  DISPATCH (retrieve block)",
            font=("Segoe UI", 10, "bold"),
            bg="#f38ba8",
            fg="#1e1e2e",
            relief="flat",
            padx=12, pady=6,
            command=self._on_dispatch
        )
        self.dispatch_btn.grid(row=0, column=3)

    def _build_log(self):
        frame = tk.LabelFrame(
            self,
            text="Event Log",
            font=("Segoe UI", 10, "bold"),
            bg="#1e1e2e",
            fg="#6c7086",
            padx=10, pady=5
        )
        frame.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self.log_text = tk.Text(
            frame,
            font=("Courier New", 9),
            bg="#313145",
            fg="#cdd6f4",
            state="disabled",
            height=6,
            yscrollcommand=scrollbar.set
        )
        self.log_text.pack(fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)

    def _on_receive(self):
        product = self.product_entry.get().strip()
        if not product:
            messagebox.showwarning(
                "Missing input", "Please enter a product name.")
            return
        self.receive_btn.config(state="disabled")
        self.dispatch_btn.config(state="disabled")
        self.controller.receive_block(product)

    def _on_dispatch(self):
        product = self.product_entry.get().strip()
        if not product:
            messagebox.showwarning(
                "Missing input", "Please enter a product name.")
            return
        self.receive_btn.config(state="disabled")
        self.dispatch_btn.config(state="disabled")
        self.controller.dispatch_block(product)

    def update_status(self, message):
        self.after(0, self._apply_update, message)

    def _apply_update(self, message):
        color = "#f38ba8" if "ERROR" in message else "#f9e2af"
        self.status_label.config(text=message[:70], fg=color)

        if self.controller.busy:
            self.wms_label.config(text="WMS: BUSY", fg="#f9e2af")
            self.receive_btn.config(state="disabled")
            self.dispatch_btn.config(state="disabled")
        else:
            self.wms_label.config(text="WMS: Ready", fg="#a6e3a1")
            self.receive_btn.config(state="normal")
            self.dispatch_btn.config(state="normal")

        # Update stock display with batch details
        lines = self.controller.warehouse.get_stock_summary()
        self.stock_text.config(state="normal")
        self.stock_text.delete("1.0", "end")
        self.stock_text.insert("1.0", "\n".join(lines))
        self.stock_text.config(state="disabled")

        # Update event log
        if self.controller.warehouse.event_log:
            self.log_text.config(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.insert("1.0", "\n".join(
                self.controller.warehouse.event_log))
            self.log_text.see("end")
            self.log_text.config(state="disabled")

    def _refresh_display(self):
        if self.controller.machine.connected and not self.controller.busy:
            try:
                conveyor = self.controller.machine.read_conveyor_state()
                lifter = self.controller.machine.read_lifter_state()

                conveyor_color = "#a6e3a1" if conveyor in (
                    101, 120, 140) else "#f9e2af"
                lifter_color = "#f9e2af" if lifter == 1 else "#a6e3a1"

                self.conveyor_label.config(
                    text=f"Conveyor: state {conveyor}",
                    fg=conveyor_color
                )
                self.lifter_label.config(
                    text=f"Lifter:   {'busy' if lifter == 1 else 'ready'}",
                    fg=lifter_color
                )
            except Exception:
                pass

        self.after(1000, self._refresh_display)

    def _connect(self):
        try:
            self.controller.connect()
            self.after(0, lambda: self.status_label.config(
                text="Connected to simulator.",
                fg="#a6e3a1"
            ))
        except Exception as e:
            self.after(0, lambda: self.status_label.config(
                text=f"Connection failed: {e}",
                fg="#f38ba8"
            ))

    def destroy(self):
        self.controller.disconnect()
        super().destroy()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    app = App()
    app.mainloop()
