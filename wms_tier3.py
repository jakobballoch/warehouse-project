"""
Warehouse Management System - Tier 3
Metropolia University of Applied Sciences
Student: Jakob Balloch

Description:
    Tracks every individual block with a unique serial number.
    Each block gets its own ID when it arrives (e.g. SN-A1B2C3D4).
    When dispatching, you can see exactly which block left the warehouse.
    Dispatched blocks are kept in history so nothing is lost.

How to run:
    1. Start the simulator: python -m block_storage_simulator --mode both
    2. Run this file:       python wms_tier3.py
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
# CLASS: Block
# Represents one individual physical block with its own serial number
# =============================================================================

class Block:
    """
    One individual block tracked by serial number.

    Every block that enters the warehouse gets a unique serial number.
    We record when it arrived and when it left.
    This gives us a full history of every single block.
    """

    def __init__(self, product_name):
        self.product_name = product_name
        self.serial_number = "SN-" + str(uuid.uuid4())[:8].upper()
        self.received_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.dispatched_at = None    # None means still in warehouse

    def dispatch(self):
        """Mark this block as dispatched and record the time."""
        self.dispatched_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def is_in_warehouse(self):
        """Return True if this block is still in stock."""
        return self.dispatched_at is None

    def __str__(self):
        if self.is_in_warehouse():
            return f"  {self.serial_number}  received={self.received_at}"
        else:
            return f"  {self.serial_number}  received={self.received_at}  dispatched={self.dispatched_at}"


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
        self.block = None    # the Block object stored here, or None if empty

    def is_empty(self):
        return self.block is None

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
            if slot.block is not None and slot.block.product_name == product_name:
                return slot
        return None

    def find_slot_with_serial(self, serial_number):
        """Find a slot that contains a block with the given serial number."""
        for slot in self.slots:
            if slot.block is not None and slot.block.serial_number == serial_number:
                return slot
        return None


# =============================================================================
# CLASS: Warehouse
# Tracks every individual block by serial number (Tier 3)
# =============================================================================

class Warehouse:
    """
    Tracks every block individually using serial numbers.

    In stock:    blocks that are currently in the warehouse
    Dispatched:  blocks that have left — kept for history

    Example:
        Receive Widget-A  →  SN-A1B2C3D4 arrives
        Receive Widget-A  →  SN-E5F6G7H8 arrives
        Dispatch Widget-A →  SN-A1B2C3D4 leaves (oldest first, FIFO)
        History still shows SN-A1B2C3D4 with dispatched timestamp
    """

    def __init__(self):
        # List of Block objects currently in the warehouse
        self.in_stock = []

        # List of Block objects that have been dispatched (history)
        self.dispatched = []

        # Event log
        self.event_log = []

    def add_block(self, product_name):
        """
        Receive one new block.
        Creates a Block with a unique serial number.
        """
        new_block = Block(product_name)
        self.in_stock.append(new_block)

        total = self.count_in_stock(product_name)
        message = (
            f"IN:  {product_name}"
            f"  serial={new_block.serial_number}"
            f"  (total: {total})"
        )
        self._log(message)
        return new_block, message

    def remove_block(self, product_name):
        """
        Dispatch one block of the given product.
        Uses FIFO — the oldest block (first in list) leaves first.
        """
        # Find the oldest block of this product still in stock
        target = None
        for block in self.in_stock:
            if block.product_name == product_name:
                target = block
                break

        if target is None:
            raise ValueError(f"No stock for '{product_name}'.")

        # Move it from in_stock to dispatched
        self.in_stock.remove(target)
        target.dispatch()
        self.dispatched.append(target)

        total = self.count_in_stock(product_name)
        message = (
            f"OUT: {product_name}"
            f"  serial={target.serial_number}"
            f"  (total: {total})"
        )
        self._log(message)
        return target, message

    def has_stock(self, product_name):
        """Check if we have at least one block of this product."""
        return self.count_in_stock(product_name) > 0

    def count_in_stock(self, product_name):
        """Count how many blocks of a product are in stock."""
        return sum(1 for b in self.in_stock if b.product_name == product_name)

    def get_stock_summary(self):
        """
        Return a list of strings showing all blocks currently in stock.
        Groups by product and shows each block's serial number.
        """
        if not self.in_stock:
            return ["(warehouse is empty)"]

        # Group blocks by product name
        products = {}
        for block in self.in_stock:
            if block.product_name not in products:
                products[block.product_name] = []
            products[block.product_name].append(block)

        lines = []
        for product_name, blocks in products.items():
            lines.append(f"{product_name}:  {len(blocks)} unit(s) in stock")
            for block in blocks:
                lines.append(
                    f"  {block.serial_number}  received={block.received_at}")

        return lines

    def get_history_summary(self):
        """
        Return a list of strings showing all dispatched blocks.
        This is the audit trail — nothing is ever deleted.
        """
        if not self.dispatched:
            return ["(no dispatched items yet)"]

        lines = ["--- Dispatch History ---"]
        for block in self.dispatched:
            lines.append(
                f"  {block.serial_number}"
                f"  product={block.product_name}"
                f"  dispatched={block.dispatched_at}"
            )
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
        self.client.open(
            target_ip=PLC_IP,
            target_ams_net_id=PLC_NET_ID,
            target_ams_port=PLC_PORT
        )
        self.connected = True

    def disconnect(self):
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
        self.client.write_symbol(self.sym_src_x, float(from_x))
        self.client.write_symbol(self.sym_src_y, float(from_y))
        self.client.write_symbol(self.sym_dst_x, float(to_x))
        self.client.write_symbol(self.sym_dst_y, float(to_y))
        time.sleep(0.05)
        self.client.write_symbol(self.sym_transfer_item, True)

    def wait_for_state(self, target_state, timeout=15):
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
    Same physical workflow as Tier 1 and 2.
    The difference is the Warehouse now tracks individual serial numbers.
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
        thread = threading.Thread(
            target=self._receive_workflow,
            args=(product_name,)
        )
        thread.daemon = True
        thread.start()

    def dispatch_block(self, product_name):
        thread = threading.Thread(
            target=self._dispatch_workflow,
            args=(product_name,)
        )
        thread.daemon = True
        thread.start()

    def _receive_workflow(self, product_name):
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

            # Create the block record with a unique serial number
            new_block, message = self.warehouse.add_block(product_name)
            slot.block = new_block
            self.on_update(f"Done! {message}")

        except Exception as error:
            self.on_update(f"ERROR: {error}")

        finally:
            self.busy = False

    def _dispatch_workflow(self, product_name):
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

            # Remove the block and record dispatch time
            dispatched_block, message = self.warehouse.remove_block(
                product_name)
            slot.block = None
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
    The main window for Tier 3.
    Shows current stock with serial numbers on the left.
    Shows dispatch history on the right.
    """

    def __init__(self):
        super().__init__()

        self.title("Warehouse Management System - Tier 3")
        self.geometry("900x620")
        self.configure(bg="#1e1e2e")

        self.controller = WMSController(on_update=self.update_status)

        self._build_title()
        self._build_main_area()
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
            text="Warehouse Management System  –  Tier 3",
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

    def _build_main_area(self):
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
        left.pack(side="left", fill="both", padx=(0, 5))

        self.conveyor_label = tk.Label(
            left, text="Conveyor: —",
            font=("Courier New", 10),
            bg="#2a2a3e", fg="#cdd6f4", anchor="w"
        )
        self.conveyor_label.pack(fill="x")

        self.lifter_label = tk.Label(
            left, text="Lifter: —",
            font=("Courier New", 10),
            bg="#2a2a3e", fg="#cdd6f4", anchor="w"
        )
        self.lifter_label.pack(fill="x")

        self.wms_label = tk.Label(
            left, text="WMS: Ready",
            font=("Courier New", 10),
            bg="#2a2a3e", fg="#a6e3a1", anchor="w"
        )
        self.wms_label.pack(fill="x")

        # Middle: current stock with serial numbers
        middle = tk.LabelFrame(
            frame,
            text="In Stock  (Tier 3 – serial number tracking)",
            font=("Segoe UI", 10, "bold"),
            bg="#2a2a3e",
            fg="#6c7086",
            padx=10, pady=10
        )
        middle.pack(side="left", fill="both", expand=True, padx=(0, 5))

        self.stock_text = tk.Text(
            middle,
            font=("Courier New", 10),
            bg="#313145",
            fg="#a6e3a1",
            state="disabled"
        )
        self.stock_text.pack(fill="both", expand=True)

        # Right: dispatch history
        right = tk.LabelFrame(
            frame,
            text="Dispatch History",
            font=("Segoe UI", 10, "bold"),
            bg="#2a2a3e",
            fg="#6c7086",
            padx=10, pady=10
        )
        right.pack(side="right", fill="both", expand=True)

        self.history_text = tk.Text(
            right,
            font=("Courier New", 10),
            bg="#313145",
            fg="#f38ba8",
            state="disabled"
        )
        self.history_text.pack(fill="both", expand=True)

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
            frame, text="Product name:",
            font=("Segoe UI", 10),
            bg="#1e1e2e", fg="#cdd6f4"
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.product_entry = tk.Entry(
            frame,
            font=("Segoe UI", 10),
            bg="#313145", fg="#cdd6f4",
            insertbackground="#cdd6f4",
            width=20
        )
        self.product_entry.insert(0, "Widget-A")
        self.product_entry.grid(row=0, column=1, padx=(0, 20))

        self.receive_btn = tk.Button(
            frame,
            text="⬇  RECEIVE (store block)",
            font=("Segoe UI", 10, "bold"),
            bg="#a6e3a1", fg="#1e1e2e",
            relief="flat", padx=12, pady=6,
            command=self._on_receive
        )
        self.receive_btn.grid(row=0, column=2, padx=(0, 10))

        self.dispatch_btn = tk.Button(
            frame,
            text="⬆  DISPATCH (retrieve block)",
            font=("Segoe UI", 10, "bold"),
            bg="#f38ba8", fg="#1e1e2e",
            relief="flat", padx=12, pady=6,
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
        frame.pack(fill="both", padx=15, pady=(0, 10))

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self.log_text = tk.Text(
            frame,
            font=("Courier New", 9),
            bg="#313145", fg="#cdd6f4",
            state="disabled", height=5,
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

        # Update stock display
        lines = self.controller.warehouse.get_stock_summary()
        self.stock_text.config(state="normal")
        self.stock_text.delete("1.0", "end")
        self.stock_text.insert("1.0", "\n".join(lines))
        self.stock_text.config(state="disabled")

        # Update dispatch history
        history = self.controller.warehouse.get_history_summary()
        self.history_text.config(state="normal")
        self.history_text.delete("1.0", "end")
        self.history_text.insert("1.0", "\n".join(history))
        self.history_text.config(state="disabled")

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
