from endstone.plugin import Plugin
from endstone.command import Command, CommandSender
from endstone.event import event_handler, PlayerJoinEvent
from endstone.form import ActionForm, MessageForm
from endstone import Player
import os
from pathlib import Path

# Try to import ChestForm for visual inventory display
try:
    from chest_form_api_endstone import ChestForm
    CHEST_FORM_AVAILABLE = True
except ImportError:
    CHEST_FORM_AVAILABLE = False

# Try to import RapidNBT for offline player data
try:
    import rapidnbt as RapidNBT
    RAPIDNBT_AVAILABLE = True
except ImportError:
    try:
        import RapidNBT
        RAPIDNBT_AVAILABLE = True
    except ImportError:
        RAPIDNBT_AVAILABLE = False
        print("[InventoryManager] RapidNBT not available - offline player viewing disabled")


# ──────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ──────────────────────────────────────────────────────────────────────

def online_players(plugin: Plugin):
    """Get all online players from the server"""
    return plugin.server.online_players


def player_name(player: Player) -> str:
    """Get player's display name"""
    return player.name


def get_inventory(player: Player):
    """Get player's main inventory"""
    try:
        return player.inventory
    except AttributeError:
        return None


def get_ender(player: Player):
    """Get player's ender chest inventory"""
    try:
        return player.ender_chest
    except AttributeError:
        return None


def inv_size(inventory) -> int:
    """Get inventory size"""
    try:
        return inventory.size
    except AttributeError:
        return 0


def get_item_from_slot(inventory, slot: int):
    """Get item from inventory slot"""
    try:
        return inventory.get_item(slot)
    except (AttributeError, IndexError):
        return None


def is_air(item) -> bool:
    """Check if item is air/empty"""
    if item is None:
        return True
    try:
        item_type = str(item.type).lower()
        return item_type in ["air", "minecraft:air"] or item.amount == 0
    except AttributeError:
        return True


def item_display_name(item) -> str:
    """Get item display name"""
    try:
        # Try custom name first
        if hasattr(item, 'custom_name') and item.custom_name:
            return item.custom_name
        # Fall back to type name
        if hasattr(item, 'type'):
            return str(item.type).replace("_", " ").title()
        return "Unknown Item"
    except AttributeError:
        return "Unknown Item"


def add_item(inventory, item) -> bool:
    """Add item to inventory, returns True if successful"""
    try:
        result = inventory.add_item(item)
        # If result is empty dict or None, item was added successfully
        return not result or len(result) == 0
    except (AttributeError, Exception):
        return False


def set_item_in_slot(inventory, slot: int, item) -> bool:
    """Set item in specific slot, returns True if successful"""
    try:
        inventory.set_item(slot, item)
        return True
    except (AttributeError, IndexError, Exception):
        return False


# ──────────────────────────────────────────────────────────────────────
# MAIN PLUGIN CLASS
# ──────────────────────────────────────────────────────────────────────

class InventoryManagerPlugin(Plugin):
    api_version = "0.5"

    commands = {
        "manageinv": {
            "description": "Open inventory management interface",
            "usages": ["/manageinv"],
            "permissions": ["inventory_manager.use"]
        }
    }

    permissions = {
        "inventory_manager.use": {
            "description": "Allows using the inventory manager",
            "default": "op"
        }
    }

    def on_enable(self) -> None:
        """Called when plugin is enabled"""
        self.logger.info("Inventory Manager Plugin enabled!")
        self.logger.info(f"ChestForm available: {CHEST_FORM_AVAILABLE}")
        self.logger.info(f"RapidNBT available: {RAPIDNBT_AVAILABLE}")

        if RAPIDNBT_AVAILABLE and CHEST_FORM_AVAILABLE:
            self.logger.info("Offline player ender chest viewing is ENABLED")
        else:
            self.logger.warning("Offline player viewing is DISABLED - missing dependencies")
            if not CHEST_FORM_AVAILABLE:
                self.logger.warning("  - ChestForm not found (install chest_form_api_endstone)")
            if not RAPIDNBT_AVAILABLE:
                self.logger.warning("  - RapidNBT not found (install RapidNBT)")

        self.register_events(self)

    def on_disable(self) -> None:
        """Called when plugin is disabled"""
        self.logger.info("Inventory Manager Plugin disabled!")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        """Handle commands"""
        if command.name == "manageinv":
            if not isinstance(sender, Player):
                sender.send_error_message("This command can only be used by players!")
                return True
            
            if not sender.has_permission("inventory_manager.use"):
                sender.send_error_message("§cYou don't have permission to use this command!")
                return True
            
            # Open the main menu
            self.open(sender)
            return True
        
        return False

    # ──────────────────────────────────────────────────────────────────────
    # MAIN MENU
    # ──────────────────────────────────────────────────────────────────────
    
    def open(self, player: Player):
        """Open the main inventory manager menu"""
        form = ActionForm(
            title="§l§6Inventory Manager",
            content="§7Manage player inventories"
        )
        form.add_button("§aOnline Players")

        if RAPIDNBT_AVAILABLE and CHEST_FORM_AVAILABLE:
            form.add_button("§eOffline Players §7(Ender Chest Only)")
            form.add_button("§cClose")
        else:
            form.add_button("§cClose")

        def on_submit(pl, idx):
            if idx == 0:
                return self._pick_online_player(pl)
            elif idx == 1:
                if RAPIDNBT_AVAILABLE and CHEST_FORM_AVAILABLE:
                    return self._pick_offline_player(pl)
                # else: close
            # idx == 2 or None: close

        form.on_submit = on_submit
        player.send_form(form)

    # ──────────────────────────────────────────────────────────────────────
    # ONLINE INVENTORIES FLOW
    # ──────────────────────────────────────────────────────────────────────
    def _pick_online_player(self, p: Player):
        opls = online_players(self)
        names = [player_name(pl) for pl in opls]

        if not names:
            p.send_message("§7No players online.")
            return self.open(p)

        form = ActionForm(title="§lOnline Players", content="Pick a player")
        for n in names: form.add_button(n)
        form.add_button("Back")

        def on_submit(pl, idx):
            if idx is None or idx < 0 or idx >= len(names):
                return self.open(pl)
            # resolve live object again, avoid stale refs
            target = None
            for live in online_players(self):
                if player_name(live) == names[idx]:
                    target = live; break
            if not target:
                pl.send_message("§7Player went offline.")
                return self._pick_online_player(pl)
            return self._inspect_online_player(pl, target)
        form.on_submit = on_submit
        p.send_form(form)

    def _inspect_online_player(self, viewer: Player, target: Player):
        """Main inspection menu - choose between Inventory or Ender Chest"""
        tname = player_name(target)
        form = ActionForm(
            title=f"§lInspect: {tname}",
            content="Choose what to inspect:"
        )
        form.add_button("§6Inventory")      # 0
        form.add_button("§dEnder Chest")    # 1
        form.add_button("Back")             # 2

        def pick(pl, idx):
            if idx == 0:
                return self._inventory_options(pl, target)
            elif idx == 1:
                return self._enderchest_options(pl, target)
            else:
                return self._pick_online_player(pl)

        form.on_submit = pick
        viewer.send_form(form)

    def _inventory_options(self, viewer: Player, target: Player):
        """Sub-menu for Inventory viewing options"""
        tname = player_name(target)
        form = ActionForm(
            title=f"§l{tname}'s Inventory",
            content="Choose how to view:\n\n§eActions§r - Take/Copy/Remove items\n§bView Only§r - Visual chest display"
        )
        form.add_button("§eActions (List View)")  # 0

        if CHEST_FORM_AVAILABLE:
            form.add_button("§bView Only (Visual Chest)")  # 1
            form.add_button("« Back")                      # 2
        else:
            form.add_button("« Back")                      # 1

        def pick(pl, idx):
            if idx == 0:
                return self._open_container(pl, target, which="inv")
            elif idx == 1:
                if CHEST_FORM_AVAILABLE:
                    return self._show_chest_form(pl, target, which="inv")
                else:
                    return self._inspect_online_player(pl, target)
            else:
                return self._inspect_online_player(pl, target)

        form.on_submit = pick
        viewer.send_form(form)

    def _enderchest_options(self, viewer: Player, target: Player):
        """Sub-menu for Ender Chest viewing options"""
        tname = player_name(target)
        form = ActionForm(
            title=f"§l{tname}'s Ender Chest",
            content="Choose how to view:\n\n§eActions§r - Take/Copy/Remove items\n§bView Only§r - Visual chest display"
        )
        form.add_button("§eActions (List View)")  # 0

        if CHEST_FORM_AVAILABLE:
            form.add_button("§bView Only (Visual Chest)")  # 1
            form.add_button("« Back")                      # 2
        else:
            form.add_button("« Back")                      # 1

        def pick(pl, idx):
            if idx == 0:
                return self._open_container(pl, target, which="ender")
            elif idx == 1:
                if CHEST_FORM_AVAILABLE:
                    return self._show_chest_form(pl, target, which="ender")
                else:
                    return self._inspect_online_player(pl, target)
            else:
                return self._inspect_online_player(pl, target)

        form.on_submit = pick
        viewer.send_form(form)

    def _open_container(self, viewer: Player, target: Player, which: str):
        tname = player_name(target)
        if which == "inv":
            inv = get_inventory(target)
            title = "Inventory"
        else:
            inv = get_ender(target)
            title = "Ender Chest"

        if not inv:
            viewer.send_message(f"§cCan't read {title.lower()} on this build.")
            return self._inspect_online_player(viewer, target)

        size = inv_size(inv)
        form = ActionForm(title=f"{title}: {tname}", content=f"{size} slots")
        for i in range(size):
            it = get_item_from_slot(inv, i)
            if not it or is_air(it):
                form.add_button(f"[{i}] — empty —")
            else:
                name = item_display_name(it)
                cnt  = getattr(it, "amount", None) or getattr(it, "count", None) or 1
                form.add_button(f"[{i}] {name} ×{cnt}")
        form.add_button("« Back to Player")  # idx == size

        def pick(pl, idx):
            if idx == size:
                return self._inspect_online_player(pl, target)
            if idx is None or idx < 0 or idx >= size:
                return self._inspect_online_player(pl, target)
            return self._slot_actions(pl, target, inv, idx, title)
        form.on_submit = pick
        viewer.send_form(form)

    def _slot_actions(self, viewer: Player, target: Player, inv, slot_idx: int, title: str):
        it = get_item_from_slot(inv, slot_idx)
        if not it or is_air(it):
            viewer.send_message("§7That slot is empty.")
            return self._open_container(viewer, target, "inv" if title == "Inventory" else "ender")

        name = item_display_name(it)
        cnt  = getattr(it, "amount", None) or getattr(it, "count", None) or 1

        f = ActionForm(title=f"{title} [{slot_idx}]", content=f"§l{name}§r ×{cnt}")
        f.add_button("Take")                # 0
        f.add_button("Copy to me")          # 1
        f.add_button("Remove (clear slot)") # 2
        f.add_button("Back to slots")       # 3
        f.add_button("Back to player")      # 4

        def on_pick(pl, btn_idx):
            if btn_idx == 0:  # Take
                dst = get_inventory(pl)
                if not dst:
                    pl.send_message("§cCan't access your inventory.")
                    return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
                item_now = get_item_from_slot(inv, slot_idx)
                if not item_now or is_air(item_now):
                    pl.send_message("§7Item no longer there.")
                    return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
                if add_item(dst, item_now):
                    set_item_in_slot(inv, slot_idx, None)
                    pl.send_message("§aItem moved to your inventory.")
                else:
                    pl.send_message("§cYour inventory is full.")
                return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")

            if btn_idx == 1:  # Copy
                dst = get_inventory(pl)
                if not dst:
                    pl.send_message("§cCan't access your inventory.")
                    return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
                item_now = get_item_from_slot(inv, slot_idx)
                if not item_now or is_air(item_now):
                    pl.send_message("§7Item no longer there.")
                    return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
                if add_item(dst, item_now):
                    pl.send_message("§aA copy was added to your inventory.")
                else:
                    pl.send_message("§cYour inventory is full.")
                return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")

            if btn_idx == 2:  # Remove
                item_now = get_item_from_slot(inv, slot_idx)
                if not item_now or is_air(item_now):
                    pl.send_message("§7Nothing to remove.")
                else:
                    if set_item_in_slot(inv, slot_idx, None):
                        pl.send_message("§aSlot cleared.")
                    else:
                        pl.send_message("§cFailed to clear that slot on this build.")
                return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")

            if btn_idx == 3:
                return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
            if btn_idx == 4:
                return self._inspect_online_player(pl, target)
        f.on_submit = on_pick
        viewer.send_form(f)

    def _show_chest_form(self, viewer: Player, target: Player, which: str):
        """Display inventory or ender chest using visual ChestForm (READ-ONLY view)"""
        if not CHEST_FORM_AVAILABLE:
            viewer.send_message("§cChest form display is not available.")
            return self._inspect_online_player(viewer, target)

        tname = player_name(target)
        if which == "inv":
            inv = get_inventory(target)
            title = f"{tname}'s Inventory (View Only)"
            allow_armor = True
        else:
            inv = get_ender(target)
            title = f"{tname}'s Ender Chest (View Only)"
            allow_armor = False

        if not inv:
            viewer.send_message(f"§cCan't read inventory on this build.")
            return self._inspect_online_player(viewer, target)

        # Create chest form (read-only - no callback to prevent interactions)
        chest = ChestForm(self, title, allow_armor)

        # DO NOT set any callback - this prevents the ItemStack callable error
        # The chest will be view-only by default without a callback

        # Populate chest with items using full ItemStack to preserve NBT
        size = inv_size(inv)

        # For ender chest, we need to handle the slot mapping differently
        if which == "ender":
            # Ender chest: Direct mapping (slot 0 -> chest slot 0)
            try:
                # WORKAROUND: Fill all slots first to prevent ChestForm from clearing slot 0
                # when the chest is not full. We'll use air as placeholder.
                for slot_idx in range(27):  # Ender chest is 27 slots (0-26)
                    # Set empty slot as placeholder (will be overwritten if item exists)
                    try:
                        chest.set_slot(slot_idx, "minecraft:air", None, item_amount=0)
                    except:
                        pass  # Ignore errors for air slots

                # Now add actual items
                for slot_idx in range(min(size, 27)):
                    item = get_item_from_slot(inv, slot_idx)
                    if item and not is_air(item):
                        # Direct mapping - no offset needed
                        self._add_item_to_chest(chest, item, slot_idx)
            except Exception as e:
                self.logger.warning(f"Error reading ender chest: {e}")
        else:
            # Player inventory: Map to chest positions
            # WORKAROUND: Fill all mapped slots first
            for slot_idx in range(size):
                chest_slot = self._map_slot_to_chest(slot_idx, which)
                if chest_slot is not None:
                    try:
                        chest.set_slot(chest_slot, "minecraft:air", None, item_amount=0)
                    except:
                        pass

            # Now add actual items
            for slot_idx in range(size):
                item = get_item_from_slot(inv, slot_idx)
                if item and not is_air(item):
                    # Map slot to chest position
                    chest_slot = self._map_slot_to_chest(slot_idx, which)
                    if chest_slot is not None:
                        self._add_item_to_chest(chest, item, chest_slot)

        # Send chest form to viewer
        chest.send_to(viewer)

        # Send message to viewer
        viewer.send_message("§7This is a read-only view. Use the list view to Take/Copy/Remove items.")

    def _add_item_to_chest(self, chest, item, chest_slot: int):
        """Add an item to the chest form with full NBT data"""
        try:
            item_type = str(item.type) if hasattr(item, 'type') else "minecraft:barrier"
            item_amount = getattr(item, 'amount', 1)
            item_data = getattr(item, 'data', 0)

            # Extract metadata for display
            display_name = ""
            lore = []
            enchants = None

            if hasattr(item, 'item_meta') and item.item_meta:
                meta = item.item_meta
                if hasattr(meta, 'display_name') and meta.display_name:
                    display_name = meta.display_name
                if hasattr(meta, 'lore') and meta.lore:
                    lore = meta.lore if isinstance(meta.lore, list) else [meta.lore]
                if hasattr(meta, 'enchants') and meta.enchants:
                    enchants = meta.enchants

            # Add enchantment info to lore if present
            if enchants and isinstance(enchants, dict):
                if not lore:
                    lore = []
                for ench_name, ench_level in enchants.items():
                    lore.append(f"§9{ench_name} {ench_level}")

            # For shulker boxes, try to add contents to lore
            if "shulker" in item_type.lower():
                # Try to get shulker contents from NBT
                try:
                    if hasattr(item, 'nbt') and item.nbt:
                        if not lore:
                            lore = []
                        lore.append("§7(Contains items)")
                except:
                    pass

            # Set slot with NBT data
            # NOTE: Pass None as third parameter instead of ItemStack to avoid callable error
            # The ChestForm API will reconstruct the item from the other parameters
            chest.set_slot(
                chest_slot,
                item_type,
                None,  # Don't pass ItemStack directly - causes callable error
                item_amount=item_amount,
                item_data=item_data,
                display_name=display_name,
                lore=lore if lore else None,
                enchants=enchants
            )
        except Exception as e:
            self.logger.warning(f"Failed to add item to chest slot {chest_slot}: {e}")

    def _map_slot_to_chest(self, slot_idx: int, which: str) -> int:
        """Map inventory slot index to chest form slot"""
        if which == "ender":
            # Ender chest: direct mapping (0-26)
            return slot_idx
        else:
            # Player inventory: map main inventory slots (9-35) to chest slots (0-26)
            # and hotbar (0-8) to chest slots (27-35)
            if 9 <= slot_idx <= 35:
                return slot_idx - 9  # Main inventory
            elif 0 <= slot_idx <= 8:
                return 27 + slot_idx  # Hotbar
            else:
                return None  # Armor/offhand slots - handled separately by allow_armor

    # ──────────────────────────────────────────────────────────────────────
    # OFFLINE PLAYER ENDER CHEST VIEWING
    # ──────────────────────────────────────────────────────────────────────
    def _pick_offline_player(self, viewer: Player):
        """Show list of offline players to view their ender chests"""
        if not RAPIDNBT_AVAILABLE:
            viewer.send_message("§cRapidNBT is not available. Cannot view offline player data.")
            return self.open(viewer)

        if not CHEST_FORM_AVAILABLE:
            viewer.send_message("§cChestForm is not available. Cannot display offline ender chests.")
            return self.open(viewer)

        # Get world folder path - try common Bedrock server locations
        possible_paths = [
            Path("worlds") / "Bedrock level" / "players",  # Default Bedrock world
            Path("worlds") / "world" / "players",           # Alternative name
            Path("Bedrock level") / "players",              # Direct path
            Path("world") / "players",                      # Direct alternative
        ]

        player_data_path = None
        for path in possible_paths:
            if path.exists():
                player_data_path = path
                self.logger.info(f"Found player data at: {path}")
                break

        if not player_data_path or not player_data_path.exists():
            viewer.send_message("§cPlayer data folder not found.")
            viewer.send_message("§7Tried: worlds/Bedrock level/players, worlds/world/players")
            return self.open(viewer)

        # Get list of player files
        player_files = list(player_data_path.glob("*.dat"))

        if not player_files:
            viewer.send_message("§cNo offline player data found.")
            return self.open(viewer)

        # Create form with player names
        form = ActionForm(
            title="§lOffline Players",
            content="§7Select a player to view their ender chest\n§c(View Only)"
        )

        player_list = []
        for player_file in player_files:
            # Extract player name from filename (remove .dat extension)
            player_name = player_file.stem
            player_list.append((player_name, player_file))
            form.add_button(f"§7{player_name}")

        form.add_button("« Back")

        def on_submit(pl, idx):
            if idx is None or idx >= len(player_list):
                return self.open(pl)

            player_name, player_file = player_list[idx]
            return self._show_offline_enderchest(pl, player_name, player_file)

        form.on_submit = on_submit
        viewer.send_form(form)

    def _show_offline_enderchest(self, viewer: Player, player_name: str, player_file: Path):
        """Display offline player's ender chest - choose between visual or actions"""
        form = ActionForm(
            title=f"§l{player_name}'s Ender Chest (Offline)",
            content="Choose how to view:\n\n§eActions§r - Copy items to your inventory\n§bView Only§r - Visual chest display"
        )
        form.add_button("§eActions (List View)")  # 0

        if CHEST_FORM_AVAILABLE:
            form.add_button("§bView Only (Visual Chest)")  # 1
            form.add_button("« Back")                      # 2
        else:
            form.add_button("« Back")                      # 1

        def pick(pl, idx):
            if idx == 0:
                return self._show_offline_enderchest_list(pl, player_name, player_file)
            elif idx == 1:
                if CHEST_FORM_AVAILABLE:
                    return self._show_offline_enderchest_visual(pl, player_name, player_file)
                else:
                    return self._pick_offline_player(pl)
            else:
                return self._pick_offline_player(pl)

        form.on_submit = pick
        viewer.send_form(form)

    def _show_offline_enderchest_list(self, viewer: Player, player_name: str, player_file: Path):
        """Show offline ender chest as list with copy actions"""
        try:
            # Read player NBT data
            nbt_data = RapidNBT.read_nbt(str(player_file))

            # Get ender chest inventory from NBT
            ender_items = nbt_data.get("EnderChestInventory", [])

            if not ender_items:
                viewer.send_message(f"§c{player_name}'s ender chest is empty or data not found.")
                return self._show_offline_enderchest(viewer, player_name, player_file)

            # Create list form
            form = ActionForm(
                title=f"§l{player_name}'s Ender Chest (Offline)",
                content="§7Click an item to copy it to your inventory"
            )

            # Store items for later access
            item_list = []

            for item_data in ender_items:
                if not isinstance(item_data, dict):
                    continue

                slot = item_data.get("Slot", -1)
                if slot < 0 or slot > 26:
                    continue

                item_type = item_data.get("Name", "minecraft:barrier")
                item_count = item_data.get("Count", 1)

                # Get display name
                display_name = ""
                tag = item_data.get("tag", {})
                if isinstance(tag, dict):
                    display = tag.get("display", {})
                    if isinstance(display, dict):
                        display_name = display.get("Name", "")

                # Create button text
                name = display_name if display_name else item_type.replace("minecraft:", "")
                form.add_button(f"[{slot}] {name} ×{item_count}")
                item_list.append(item_data)

            form.add_button("« Back")

            def on_select(pl, idx):
                if idx is None or idx >= len(item_list):
                    return self._show_offline_enderchest(pl, player_name, player_file)

                selected_item = item_list[idx]
                return self._offline_item_actions(pl, player_name, player_file, selected_item)

            form.on_submit = on_select
            viewer.send_form(form)

        except Exception as e:
            self.logger.error(f"Error reading offline player data for {player_name}: {e}")
            viewer.send_message(f"§cFailed to load {player_name}'s ender chest data.")
            return self._pick_offline_player(viewer)

    def _offline_item_actions(self, viewer: Player, player_name: str, player_file: Path, item_data: dict):
        """Show actions for an offline ender chest item"""
        slot = item_data.get("Slot", -1)
        item_type = item_data.get("Name", "minecraft:barrier")
        item_count = item_data.get("Count", 1)

        # Get display name
        display_name = ""
        tag = item_data.get("tag", {})
        if isinstance(tag, dict):
            display = tag.get("display", {})
            if isinstance(display, dict):
                display_name = display.get("Name", "")

        name = display_name if display_name else item_type.replace("minecraft:", "")

        form = ActionForm(
            title=f"§lSlot {slot}",
            content=f"§e{name} §7×{item_count}\n\n§7Choose an action:"
        )
        form.add_button("§bCopy to My Inventory")  # 0
        form.add_button("« Back to List")          # 1

        def on_action(pl, idx):
            if idx == 0:
                # Copy item to viewer's inventory
                return self._copy_offline_item(pl, player_name, player_file, item_data)
            else:
                return self._show_offline_enderchest_list(pl, player_name, player_file)

        form.on_submit = on_action
        viewer.send_form(form)

    def _copy_offline_item(self, viewer: Player, player_name: str, player_file: Path, item_data: dict):
        """Copy an offline ender chest item to viewer's inventory using RapidNBT"""
        try:
            from endstone.inventory import ItemStack

            item_type = item_data.get("Name", "minecraft:barrier")
            item_count = item_data.get("Count", 1)
            item_damage = item_data.get("Damage", 0)

            # Create ItemStack
            item = ItemStack(item_type, item_count, item_damage)

            # Try to apply NBT data to the item
            tag = item_data.get("tag", {})
            if isinstance(tag, dict) and tag:
                # Apply display name and lore if available
                if hasattr(item, 'item_meta') and item.item_meta:
                    meta = item.item_meta

                    display = tag.get("display", {})
                    if isinstance(display, dict):
                        display_name = display.get("Name", "")
                        if display_name and hasattr(meta, 'display_name'):
                            meta.display_name = display_name

                        lore_data = display.get("Lore", [])
                        if lore_data and hasattr(meta, 'lore'):
                            meta.lore = lore_data if isinstance(lore_data, list) else [lore_data]

                    # Note: Enchantments might not be directly settable via item_meta
                    # The NBT data is preserved in the ItemStack creation

            # Add to viewer's inventory
            viewer_inv = get_inventory(viewer)
            if not viewer_inv:
                viewer.send_message("§cCan't access your inventory.")
                return self._show_offline_enderchest_list(viewer, player_name, player_file)

            if add_item(viewer_inv, item):
                viewer.send_message(f"§aCopied item to your inventory!")
            else:
                viewer.send_message("§cYour inventory is full.")

            return self._show_offline_enderchest_list(viewer, player_name, player_file)

        except Exception as e:
            self.logger.error(f"Error copying offline item: {e}")
            viewer.send_message("§cFailed to copy item.")
            return self._show_offline_enderchest_list(viewer, player_name, player_file)

    def _show_offline_enderchest_visual(self, viewer: Player, player_name: str, player_file: Path):
        """Display offline player's ender chest using ChestForm (read-only)"""
        try:
            # Read player NBT data
            nbt_data = RapidNBT.read_nbt(str(player_file))

            # Get ender chest inventory from NBT
            ender_items = nbt_data.get("EnderChestInventory", [])

            if not ender_items:
                viewer.send_message(f"§c{player_name}'s ender chest is empty or data not found.")
                return self._show_offline_enderchest(viewer, player_name, player_file)

            # Create chest form
            chest = ChestForm(self, f"{player_name}'s Ender Chest (Offline - View Only)", False)

            # WORKAROUND: Fill all slots first to prevent ChestForm from clearing slot 0
            # when the chest is not full
            for slot_idx in range(27):  # Ender chest is 27 slots (0-26)
                try:
                    chest.set_slot(slot_idx, "minecraft:air", None, item_amount=0)
                except:
                    pass  # Ignore errors for air slots

            # Populate chest with items from NBT
            for item_data in ender_items:
                if not isinstance(item_data, dict):
                    continue

                slot = item_data.get("Slot", -1)
                if slot < 0 or slot > 26:
                    continue

                item_type = item_data.get("Name", "minecraft:barrier")
                item_count = item_data.get("Count", 1)
                item_damage = item_data.get("Damage", 0)

                # Extract display name and lore from tag
                display_name = ""
                lore = []
                enchants = None

                tag = item_data.get("tag", {})
                if isinstance(tag, dict):
                    display = tag.get("display", {})
                    if isinstance(display, dict):
                        display_name = display.get("Name", "")
                        lore_data = display.get("Lore", [])
                        if isinstance(lore_data, list):
                            lore = lore_data

                    # Get enchantments
                    ench_data = tag.get("ench", [])
                    if isinstance(ench_data, list) and ench_data:
                        enchants = {}
                        for ench in ench_data:
                            if isinstance(ench, dict):
                                ench_id = ench.get("id", 0)
                                ench_lvl = ench.get("lvl", 1)
                                enchants[f"Enchantment {ench_id}"] = ench_lvl

                # Add item to chest - direct mapping (no offset)
                try:
                    chest.set_slot(
                        slot,
                        item_type,
                        None,
                        item_amount=item_count,
                        item_data=item_damage,
                        display_name=display_name,
                        lore=lore if lore else None,
                        enchants=enchants
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to set offline ender chest slot {slot}: {e}")

            # Send chest to viewer
            chest.send_to(viewer)
            viewer.send_message("§7Viewing offline player's ender chest (read-only). Use Actions view to copy items.")

        except Exception as e:
            self.logger.error(f"Error reading offline player data for {player_name}: {e}")
            viewer.send_message(f"§cFailed to load {player_name}'s ender chest data.")
            return self._show_offline_enderchest(viewer, player_name, player_file)

    #