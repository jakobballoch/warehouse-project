"""
Warehouse Management System - Tier 1
Metropolia University of Applied Sciences
Student: Jakob Balloch

Description:
    A simple warehouse system that tracks how many blocks
    are stored for each product. Connects to the block storage
    simulator using the ADS protocol.

How to run:
    1. Start the simulator: python -m block_storage_simulator --mode both
    2. Run this file:       python wms_tier1.py
"""

import tkinter as tk
from tkinter import messagebox
import threading
import time

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

# ── Physical measurements (millimetres) ──────────────────────────────────────

BLOCK_SIZE = 60      # each block is 60x60 mm
AREA_WIDTH = 400     # storage area is 400 mm wide
AREA_HEIGHT = 300     # storage area is 300 mm tall
PALLET_X = 160.0   # pallet centre X when at transfer slot
PALLET_Y = 410.0   # pallet centre Y when at transfer slot


# =============================================================================
# CLASS: StorageSlot
# Represents one physical position in the storage grid
# =============================================================================

class StorageSlot:
    """One grid position where a block can be stored."""

    def __init__(self, column, row, x, y):
        self.column = column
        self.row = row
        self.x = x        # physical X position in mm
        self.y = y        # physical Y position in mm
        self.product = None     # None means the slot is empty

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

        columns = AREA_WIDTH // BLOCK_SIZE   # = 6
        rows = AREA_HEIGHT // BLOCK_SIZE   # = 5

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
# Tracks how many of each product we have in stock (Tier 1 = bulk quantity)
# =============================================================================

class Warehouse:
    """
    Keeps track of product quantities.
    Tier 1: we only care about HOW MANY of each product we have.
    """

    def __init__(self):
        # Dictionary: product name → quantity
        # Example: {"Widget-A": 3, "Widget-B": 1}
        self.stock = {}

        # List of events so the user can see what happened
        self.event_log = []

    def add_item(self, product_name):
        """Add one unit of a product to stock."""
        if product_name not in self.stock:
            self.stock[product_name] = 0

        self.stock[product_name] += 1

        message = f"IN:  {product_name}  →  total now {self.stock[product_name]}"
        self._log(message)
        return message

    def remove_item(self, product_name):
        """Remove one unit of a product from stock."""
        if product_name not in self.stock or self.stock[product_name] == 0:
            raise ValueError(f"No stock available for '{product_name}'")

        self.stock[product_name] -= 1

        message = f"OUT: {product_name}  →  total now {self.stock[product_name]}"
        self._log(message)
        return message

    def has_stock(self, product_name):
        """Check if we have at least one unit of a product."""
        return self.stock.get(product_name, 0) > 0

    def get_stock_summary(self):
        """Return a list of strings showing current stock."""
        if not self.stock:
            return ["(warehouse is empty)"]

        lines = []
        for name, qty in self.stock.items():
            lines.append(f"{name}:  {qty} unit(s)")
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

        # ADS symbols - these are the variable names the machine understands
        self.sym_conveyor_state = ADSSymbol(
            "StatusVars.ConveyorState",       INT)
        self.sym_lifter_state = ADSSymbol(
            "StatusVars.LifterState",         INT)
        self.sym_send_pallet = ADSSymbol(
            "Remote.send_pallet",             BOOL)
        self.sym_release_imaging = ADSSymbol(
            "Remote.release_from_imaging",    BOOL)
        self.sym_return_pallet = ADSSymbol(
            "Remote.return_pallet",           BOOL)
        self.sym_transfer_item = ADSSymbol(
            "Remote.transfer_item",           BOOL)
        self.sym_src_x = ADSSymbol("Remote.src_x",                   LREAL)
        self.sym_src_y = ADSSymbol("Remote.src_y",                   LREAL)
        self.sym_dst_x = ADSSymbol("Remote.dst_x",                   LREAL)
        self.sym_dst_y = ADSSymbol("Remote.dst_y",                   LREAL)

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
        """Read what state the conveyor is in right now."""
        return int(self.client.read_symbol(self.sym_conveyor_state))

    def read_lifter_state(self):
        """Read what state the lifter is in right now."""
        return int(self.client.read_symbol(self.sym_lifter_state))

    def send_pallet(self):
        """Tell the conveyor to move the pallet from home toward imaging."""
        self.client.write_symbol(self.sym_send_pallet, True)

    def release_from_imaging(self):
        """Tell the conveyor to move the pallet from imaging to transfer slot."""
        self.client.write_symbol(self.sym_release_imaging, True)

    def return_pallet(self):
        """Tell the conveyor to bring the pallet back home."""
        self.client.write_symbol(self.sym_return_pallet, True)

    def transfer_item(self, from_x, from_y, to_x, to_y):
        """
        Tell the lifter to pick up a block from one position
        and place it at another position.
        Coordinates must be set BEFORE sending the command.
        """
        self.client.write_symbol(self.sym_src_x, float(from_x))
        self.client.write_symbol(self.sym_src_y, float(from_y))
        self.client.write_symbol(self.sym_dst_x, float(to_x))
        self.client.write_symbol(self.sym_dst_y, float(to_y))
        time.sleep(0.05)   # short pause to let coordinates settle
        self.client.write_symbol(self.sym_transfer_item, True)

    def wait_for_state(self, target_state, timeout=15):
        """
        Keep checking the conveyor state until it matches target_state.
        Returns True if reached, False if timed out.
        """
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
    Tells the machine what to do step by step.
    """

    def __init__(self, on_update):
        self.machine = MachineConnection()
        self.warehouse = Warehouse()
        self.grid = StorageGrid()
        self.on_update = on_update   # function to call when UI needs refreshing
        self.busy = False

    def connect(self):
        """Connect to the simulator."""
        self.machine.connect()
        self.on_update("Connected to simulator.")

    def disconnect(self):
        """Disconnect from the simulator."""
        self.machine.disconnect()

    def receive_block(self, product_name):
        """
        Full workflow to store one block in the warehouse.

        Steps:
        1. Wait for pallet to be at home
        2. Send pallet to imaging
        3. Release from imaging to transfer slot
        4. Move block from pallet to a free storage slot
        5. Return pallet home
        6. Update stock records
        """
        # Run in background so the GUI doesn't freeze
        thread = threading.Thread(
            target=self._receive_workflow,
            args=(product_name,)
        )
        thread.daemon = True
        thread.start()

    def dispatch_block(self, product_name):
        """
        Full workflow to retrieve one block from the warehouse.

        Steps:
        1. Check we have stock
        2. Wait for pallet to be at home
        3. Send pallet to imaging
        4. Release from imaging to transfer slot
        5. Move block from storage slot to pallet
        6. Return pallet home
        7. Update stock records
        """
        thread = threading.Thread(
            target=self._dispatch_workflow,
            args=(product_name,)
        )
        thread.daemon = True
        thread.start()

    def _receive_workflow(self, product_name):
        """The actual receive steps (runs in background thread)."""
        if self.busy:
            self.on_update("Busy! Wait for current operation to finish.")
            return

        self.busy = True

        try:
            # Step 1: find a free slot before doing anything physical
            slot = self.grid.get_next_free_slot()
            if slot is None:
                self.on_update("ERROR: Storage is full!")
                return

            # Step 2: wait for pallet at home
            self.on_update("Waiting for pallet at home...")
            ok = self.machine.wait_for_state(STATE_AT_HOME)
            if not ok:
                self.on_update("ERROR: Timed out waiting for home.")
                return

            # Step 3: send pallet to imaging
            self.on_update("Sending pallet to imaging...")
            self.machine.send_pallet()
            ok = self.machine.wait_for_state(STATE_AT_IMAGING)
            if not ok:
                self.on_update("ERROR: Timed out waiting for imaging.")
                return

            # Step 4: release from imaging to transfer slot
            self.on_update("Moving to transfer slot...")
            self.machine.release_from_imaging()
            ok = self.machine.wait_for_state(STATE_AT_SLOT)
            if not ok:
                self.on_update("ERROR: Timed out waiting for transfer slot.")
                return

            # Step 5: pause so block is visible in transfer slot
            # The lifter cannot reach from home directly to storage.
            # The block must first be in the transfer slot, then the
            # lifter moves it from the transfer slot to the storage slot.
            self.on_update(
                "Block arrived at transfer slot - lifter preparing...")
            time.sleep(2.0)

            # Step 6: move block from transfer slot to storage slot
            self.on_update(
                f"Lifter moving block to storage slot {slot.label()}...")
            self.machine.transfer_item(PALLET_X, PALLET_Y, slot.x, slot.y)

            # Step 7: return pallet home
            self.on_update("Returning pallet home...")
            self.machine.return_pallet()
            ok = self.machine.wait_for_state(STATE_AT_HOME)
            if not ok:
                self.on_update("ERROR: Timed out returning home.")
                return

            # Step 7: update records
            slot.product = product_name
            message = self.warehouse.add_item(product_name)
            self.on_update(f"Done! {message}")

        except Exception as error:
            self.on_update(f"ERROR: {error}")

        finally:
            self.busy = False

    def _dispatch_workflow(self, product_name):
        """The actual dispatch steps (runs in background thread)."""
        if self.busy:
            self.on_update("Busy! Wait for current operation to finish.")
            return

        self.busy = True

        try:
            # Step 1: check we have stock
            if not self.warehouse.has_stock(product_name):
                self.on_update(f"ERROR: No stock for '{product_name}'.")
                return

            # Step 2: find which slot holds this product
            slot = self.grid.find_slot_with_product(product_name)
            if slot is None:
                self.on_update(
                    f"ERROR: Could not find '{product_name}' in storage.")
                return

            # Step 3: wait for pallet at home
            self.on_update("Waiting for pallet at home...")
            ok = self.machine.wait_for_state(STATE_AT_HOME)
            if not ok:
                self.on_update("ERROR: Timed out waiting for home.")
                return

            # Step 4: send pallet to imaging
            self.on_update("Sending pallet to imaging...")
            self.machine.send_pallet()
            ok = self.machine.wait_for_state(STATE_AT_IMAGING)
            if not ok:
                self.on_update("ERROR: Timed out waiting for imaging.")
                return

            # Step 5: release from imaging to transfer slot
            self.on_update("Moving to transfer slot...")
            self.machine.release_from_imaging()
            ok = self.machine.wait_for_state(STATE_AT_SLOT)
            if not ok:
                self.on_update("ERROR: Timed out waiting for transfer slot.")
                return

            # Step 6: move block from storage slot to transfer slot (pallet)
            # The lifter picks the block from storage and places it
            # onto the pallet which is waiting in the transfer slot.
            self.on_update(
                f"Lifter retrieving block from slot {slot.label()}...")
            self.machine.transfer_item(slot.x, slot.y, PALLET_X, PALLET_Y)

            # Pause so the block is visibly on the pallet in the transfer slot
            self.on_update(
                "Block placed on pallet in transfer slot - returning home...")
            time.sleep(2.0)

            # Step 7: return pallet home
            self.on_update("Returning pallet home...")
            self.machine.return_pallet()
            ok = self.machine.wait_for_state(STATE_AT_HOME)
            if not ok:
                self.on_update("ERROR: Timed out returning home.")
                return

            # Step 8: update records
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
    The main window of the Warehouse Management System.

    Layout:
    ┌─────────────────────────────────────┐
    │  Title                              │
    ├──────────────┬──────────────────────┤
    │  Status      │  Stock               │
    │  (machine)   │  (inventory)         │
    ├──────────────┴──────────────────────┤
    │  Controls (product entry + buttons) │
    ├─────────────────────────────────────┤
    │  Event log                          │
    └─────────────────────────────────────┘
    """

    def __init__(self):
        super().__init__()

        self.title("Warehouse Management System - Tier 1")
        self.geometry("700x550")
        self.configure(bg="#1e1e2e")

        # Create the controller
        self.controller = WMSController(on_update=self.update_status)

        # Build all the UI sections
        self._build_title()
        self._build_status_and_stock()
        self._build_controls()
        self._build_log()

        # Connect to simulator in background
        thread = threading.Thread(target=self._connect)
        thread.daemon = True
        thread.start()

        # Refresh the display every second
        self._refresh_display()

    # ── UI builder methods ────────────────────────────────────────────────────

    def _build_title(self):
        """Top title bar."""
        frame = tk.Frame(self, bg="#1e1e2e")
        frame.pack(fill="x", padx=15, pady=10)

        tk.Label(
            frame,
            text="Warehouse Management System  –  Tier 1",
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
        """Middle section: machine status on left, stock on right."""
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

        # Right: stock
        right = tk.LabelFrame(
            frame,
            text="Stock  (Tier 1 – quantity tracking)",
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
            height=6
        )
        self.stock_text.pack(fill="both", expand=True)

    def _build_controls(self):
        """Product entry and receive/dispatch buttons."""
        frame = tk.LabelFrame(
            self,
            text="Operations",
            font=("Segoe UI", 10, "bold"),
            bg="#1e1e2e",
            fg="#6c7086",
            padx=10, pady=10
        )
        frame.pack(fill="x", padx=15, pady=5)

        # Product name entry
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

        # Receive button
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

        # Dispatch button
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
        """Scrollable event log at the bottom."""
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

    # ── Button handlers ───────────────────────────────────────────────────────

    def _on_receive(self):
        """Called when user clicks RECEIVE."""
        product = self.product_entry.get().strip()
        if not product:
            messagebox.showwarning(
                "Missing input", "Please enter a product name.")
            return
        self.receive_btn.config(state="disabled")
        self.dispatch_btn.config(state="disabled")
        self.controller.receive_block(product)

    def _on_dispatch(self):
        """Called when user clicks DISPATCH."""
        product = self.product_entry.get().strip()
        if not product:
            messagebox.showwarning(
                "Missing input", "Please enter a product name.")
            return
        self.receive_btn.config(state="disabled")
        self.dispatch_btn.config(state="disabled")
        self.controller.dispatch_block(product)

    # ── Display update methods ────────────────────────────────────────────────

    def update_status(self, message):
        """Called by the controller whenever something happens."""
        # Use after() so GUI updates happen on the main thread
        self.after(0, self._apply_update, message)

    def _apply_update(self, message):
        """Actually update the UI (must run on main thread)."""
        # Update status bar
        color = "#f38ba8" if "ERROR" in message else "#f9e2af"
        self.status_label.config(text=message[:70], fg=color)

        # Update WMS busy indicator
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

        # Add to event log
        if self.controller.warehouse.event_log:
            self.log_text.config(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.insert("1.0", "\n".join(
                self.controller.warehouse.event_log))
            self.log_text.see("end")
            self.log_text.config(state="disabled")

    def _refresh_display(self):
        """Poll the machine state every second to keep display fresh."""
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

        # Schedule next refresh
        self.after(1000, self._refresh_display)

    def _connect(self):
        """Connect to the simulator (runs in background)."""
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
        """Clean up when window is closed."""
        self.controller.disconnect()
        super().destroy()


# =============================================================================
# MAIN - start the application
# =============================================================================

if __name__ == "__main__":
    app = App()
    app.mainloop()
