"""TopologyMixin implementation slice."""

from .winapi import *


class TopologyMixin:
    def _filetime_to_int(self, value):
        return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

    def _iter_mask_bits(self, mask):
        value = int(mask)
        index = 0
        while value:
            if value & 1:
                yield index
            value >>= 1
            index += 1

    def _enumerate_cpu_sets(self):
        needed = wintypes.ULONG()
        kernel32.GetSystemCpuSetInformation(None, 0, ctypes.byref(needed), None, 0)
        if not needed.value:
            self._note_capability("GetSystemCpuSetInformation did not return topology data. CPU Sets optimizations are disabled.")
            return []

        buffer = ctypes.create_string_buffer(needed.value)
        if not kernel32.GetSystemCpuSetInformation(buffer, needed.value, ctypes.byref(needed), None, 0):
            self._log_once(("cpu_sets", ctypes.get_last_error()), f"[WARN] GetSystemCpuSetInformation failed: {self._last_error_text()}")
            return []

        cpu_sets = []
        offset = 0
        while offset < needed.value:
            record = ctypes.cast(ctypes.byref(buffer, offset), ctypes.POINTER(SYSTEM_CPU_SET_INFORMATION)).contents
            if record.Type == CpuSetInformation:
                flags = int(record.CpuSet.AllFlags)
                logical_index = int(record.CpuSet.LogicalProcessorIndex)
                cpu_sets.append(
                    {
                        "id": int(record.CpuSet.Id),
                        "group": int(record.CpuSet.Group),
                        "logical_index": logical_index,
                        "core_index": int(record.CpuSet.CoreIndex),
                        "llc_index": int(record.CpuSet.LastLevelCacheIndex),
                        "numa_index": int(record.CpuSet.NumaNodeIndex),
                        "efficiency_class": int(record.CpuSet.EfficiencyClass),
                        "parked": bool(flags & 0x1),
                        "allocated": bool(flags & 0x2),
                        "allocated_to_target_process": bool(flags & 0x4),
                        "realtime": bool(flags & 0x8),
                        "scheduling_class": int(record.CpuSet.SchedulingClass),
                    }
                )
            if not record.Size:
                break
            offset += int(record.Size)
        return cpu_sets

    def _enumerate_cache_relationships(self):
        needed = wintypes.DWORD()
        kernel32.GetLogicalProcessorInformationEx(RelationCache, None, ctypes.byref(needed))
        if not needed.value:
            return []

        buffer = ctypes.create_string_buffer(needed.value)
        if not kernel32.GetLogicalProcessorInformationEx(RelationCache, buffer, ctypes.byref(needed)):
            self._log_once(("cache_relationships", ctypes.get_last_error()), f"[WARN] GetLogicalProcessorInformationEx failed: {self._last_error_text()}")
            return []

        relationships = []
        offset = 0
        buffer_address = ctypes.addressof(buffer)
        group_masks_offset = SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX_CACHE.Cache.offset + CACHE_RELATIONSHIP.GroupMasks.offset

        while offset < needed.value:
            header = ctypes.cast(ctypes.byref(buffer, offset), ctypes.POINTER(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)).contents
            if header.Relationship == RelationCache:
                record = ctypes.cast(ctypes.byref(buffer, offset), ctypes.POINTER(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX_CACHE)).contents
                if int(record.Cache.Level) == 3:
                    group_count = max(1, int(record.Cache.GroupCount))
                    masks_type = GROUP_AFFINITY * group_count
                    masks = ctypes.cast(buffer_address + offset + group_masks_offset, ctypes.POINTER(masks_type)).contents
                    relationships.append(
                        {
                            "level": int(record.Cache.Level),
                            "cache_size": int(record.Cache.CacheSize),
                            "group_masks": [{"group": int(mask.Group), "mask": int(mask.Mask)} for mask in masks],
                        }
                    )
            if not header.Size:
                break
            offset += int(header.Size)
        return relationships

    def _score_core_group(self, core):
        return (
            0 if core["parked"] else 1,
            core["efficiency_class"],
            core["l3_size"],
            -core["group"],
            -core["core_index"],
        )

    def _score_llc_group(self, llc):
        return (
            llc["l3_size"],
            llc["efficiency_class"],
            len(llc["core_keys"]),
            -llc["group"],
            -llc["llc_index"],
        )

    def _refresh_topology(self, reason="periodic"):
        # WHY (item 11): Serialize the whole rebuild under _topology_lock so two
        # threads (monitor + API refresh) cannot interleave their Win32
        # enumeration and field rebinds. The lock is re-entrant-safe here
        # because nothing called within re-acquires it. Fall back gracefully if
        # the lock attribute is somehow absent (older test doubles).
        lock = getattr(self, "_topology_lock", None)
        if lock is None:
            self._build_topology_map()
            self._select_cpu_partitions()
            self._last_topology_refresh = time.monotonic()
            return self._topology
        with lock:
            self._build_topology_map()
            self._select_cpu_partitions()
            self._last_topology_refresh = time.monotonic()
            return self._topology

    def _build_topology_map(self):
        # WHY (item 11): Build everything into LOCALS first (the Win32
        # enumeration here can take many ms), then rebind the shared fields
        # under _state_lock in one short critical section so the API thread
        # never observes a half-updated _topology / _cpu_sets_by_id pair.
        cpu_sets = self._enumerate_cpu_sets()
        cpu_sets_by_id = {cpu["id"]: cpu for cpu in cpu_sets}
        if not cpu_sets:
            topology = {"cpu_sets": [], "core_groups": [], "llc_groups": [], "heterogeneous_efficiency": False, "multi_llc": False}
            with self._state_lock:
                self._cpu_sets_by_id = cpu_sets_by_id
                self._topology = topology
            return topology

        l3_size_by_cpu = {}
        for relationship in self._enumerate_cache_relationships():
            for group_mask in relationship["group_masks"]:
                for logical_index in self._iter_mask_bits(group_mask["mask"]):
                    l3_size_by_cpu[(group_mask["group"], logical_index)] = max(
                        relationship["cache_size"],
                        l3_size_by_cpu.get((group_mask["group"], logical_index), 0),
                    )

        core_groups = {}
        llc_groups = {}
        for cpu in cpu_sets:
            cpu["l3_size"] = l3_size_by_cpu.get((cpu["group"], cpu["logical_index"]), 0)
            key = (cpu["group"], cpu["core_index"])
            core = core_groups.setdefault(
                key,
                {
                    "key": key,
                    "group": cpu["group"],
                    "core_index": cpu["core_index"],
                    "llc_key": (cpu["group"], cpu["llc_index"]),
                    "llc_index": cpu["llc_index"],
                    "efficiency_class": cpu["efficiency_class"],
                    "cpu_set_ids": [],
                    "logical_indices": [],
                    "parked": True,
                    "allocated": False,
                    "realtime": False,
                    "l3_size": 0,
                },
            )
            core["cpu_set_ids"].append(cpu["id"])
            core["logical_indices"].append(cpu["logical_index"])
            core["efficiency_class"] = max(core["efficiency_class"], cpu["efficiency_class"])
            core["parked"] = core["parked"] and cpu["parked"]
            core["allocated"] = core["allocated"] or cpu["allocated"]
            core["realtime"] = core["realtime"] or cpu["realtime"]
            core["l3_size"] = max(core["l3_size"], cpu["l3_size"])

        for core in core_groups.values():
            llc = llc_groups.setdefault(
                core["llc_key"],
                {
                    "key": core["llc_key"],
                    "group": core["group"],
                    "llc_index": core["llc_index"],
                    "l3_size": 0,
                    "core_keys": [],
                    "efficiency_class": 0,
                },
            )
            llc["core_keys"].append(core["key"])
            llc["l3_size"] = max(llc["l3_size"], core["l3_size"])
            llc["efficiency_class"] = max(llc["efficiency_class"], core["efficiency_class"])

        sorted_cores = sorted(core_groups.values(), key=self._score_core_group, reverse=True)
        llc_cache_sizes = {key: value["l3_size"] for key, value in llc_groups.items()}
        topology = {
            "cpu_sets": cpu_sets,
            "core_groups": sorted_cores,
            "llc_groups": sorted(llc_groups.values(), key=self._score_llc_group, reverse=True),
            "heterogeneous_efficiency": len({core["efficiency_class"] for core in sorted_cores}) > 1,
            "multi_llc": len(llc_groups) > 1,
        }
        # WHY (item 11): Single short critical section to publish the rebuilt
        # topology atomically for concurrent API readers.
        with self._state_lock:
            self._cpu_sets_by_id = cpu_sets_by_id
            self._llc_cache_sizes = llc_cache_sizes
            self._topology = topology
        return topology

    def _select_cpu_partitions(self):
        # WHY (item 11): Read the current topology atomically; if it is missing
        # rebuild it (that path self-locks). Partitions are computed into a
        # local and published under _state_lock so the API thread never reads a
        # _cpu_partitions dict that is mid-mutation.
        with self._state_lock:
            topology = self._topology
        if not topology:
            topology = self._build_topology_map()
        core_groups = list(topology.get("core_groups", []))
        if not core_groups:
            empty = {"game": [], "background": [], "housekeeping": [], "game_cores": []}
            with self._state_lock:
                self._cpu_partitions = empty
            return empty

        if len(core_groups) == 1:
            self._note_capability("Single-core system detected: CPU isolation is ineffective. Only priority adjustments will be applied.")

        total_cores = len(core_groups)
        housekeeping_count = (
            min(self.housekeeping_core_count, max(0, total_cores - 2))
            if total_cores > 4
            else 0
        )
        game_cores = []
        housekeeping_cores = []
        background_cores = []

        preferred_llc = topology["llc_groups"][0] if topology.get("multi_llc") and topology.get("llc_groups") else None
        if preferred_llc and len(topology["llc_groups"]) > 1:
            self._log_once(
                ("preferred_llc_group", preferred_llc["group"], preferred_llc["llc_index"]),
                (
                    "[INFO] Selected LLC group "
                    f"group={preferred_llc['group']} llc={preferred_llc['llc_index']} "
                    "for game CPU partition."
                ),
            )
            game_cores = [core for core in core_groups if core["llc_key"] == preferred_llc["key"]]
            remaining = [core for core in core_groups if core["llc_key"] != preferred_llc["key"]]
            housekeeping_cores = remaining[: min(housekeeping_count, max(0, len(remaining) - 1))]
            background_cores = remaining[len(housekeeping_cores) :]
        elif topology.get("heterogeneous_efficiency"):
            top_efficiency = max(core["efficiency_class"] for core in core_groups)
            game_cores = [core for core in core_groups if core["efficiency_class"] == top_efficiency]
            remaining = [core for core in core_groups if core["efficiency_class"] != top_efficiency]
            housekeeping_cores = remaining[: min(housekeeping_count, max(0, len(remaining) - 1))]
            background_cores = remaining[len(housekeeping_cores) :]
        else:
            if total_cores <= 4:
                background_count = 1 if total_cores >= 3 else 0
            else:
                background_count = max(1, total_cores // 4)
            game_count = max(1, total_cores - housekeeping_count - background_count)
            game_cores = core_groups[:game_count]
            housekeeping_cores = core_groups[game_count : game_count + housekeeping_count]
            background_cores = core_groups[game_count + housekeeping_count :]

        # WHY (item 9): On exactly-2-core machines the salvage used to be gated
        # `total_cores > 2`, leaving the background partition EMPTY so jailed
        # processes had no dedicated background core to be pinned to. Allow the
        # salvage whenever there are at least 2 cores and more than one game
        # core, carving one background core out. The `len(game_cores) > 1`
        # guard still protects the 1-core path (which keeps its single core
        # entirely for the game).
        if not background_cores and len(game_cores) > 1 and total_cores >= 2:
            background_cores = [game_cores.pop()]
        if not housekeeping_cores and len(game_cores) > 1 and total_cores > 4:
            housekeeping_cores = [game_cores.pop()]
        if not game_cores and housekeeping_cores:
            game_cores = [housekeeping_cores.pop(0)]
        if not game_cores and background_cores:
            game_cores = [background_cores.pop(0)]

        def flatten(cores):
            ids = []
            for core in cores:
                ids.extend(core["cpu_set_ids"])
            return ids

        partitions = {
            "game": flatten(game_cores),
            "background": flatten(background_cores),
            "housekeeping": flatten(housekeeping_cores),
            "game_cores": game_cores,
        }
        # WHY (item 11): Publish atomically for concurrent API readers.
        with self._state_lock:
            self._cpu_partitions = partitions
        return partitions

    def _get_process_default_cpu_sets(self, handle):
        required = wintypes.ULONG()
        kernel32.GetProcessDefaultCpuSets(handle, None, 0, ctypes.byref(required))
        if not required.value:
            return []
        buffer = (wintypes.ULONG * required.value)()
        if not kernel32.GetProcessDefaultCpuSets(handle, buffer, required.value, ctypes.byref(required)):
            return []
        return [int(buffer[index]) for index in range(required.value)]

    def _set_process_default_cpu_sets(self, handle, cpu_set_ids):
        if cpu_set_ids:
            buffer = (wintypes.ULONG * len(cpu_set_ids))(*[int(cpu_set_id) for cpu_set_id in cpu_set_ids])
            return bool(kernel32.SetProcessDefaultCpuSets(handle, buffer, len(cpu_set_ids)))
        return bool(kernel32.SetProcessDefaultCpuSets(handle, None, 0))

    def _apply_process_affinity_fallback(self, handle, cpu_set_ids):
        masks_by_group = {}
        for cpu_set_id in cpu_set_ids:
            cpu = self._cpu_sets_by_id.get(int(cpu_set_id))
            if not cpu:
                continue
            masks_by_group.setdefault(cpu["group"], 0)
            # WHY (item 8): A process affinity mask is RELATIVE to the processor
            # group — bit 0 is the first logical processor IN THAT GROUP, not
            # the system-wide logical index. Using the raw logical_index shifts
            # past the 64-bit mask on machines with >64 logical processors
            # (c_size_t silently truncates, producing a zero/wrong mask), so
            # compute the group-relative bit exactly like the thread-level
            # fallback in _apply_thread_affinity_fallback does.
            masks_by_group[cpu["group"]] |= 1 << (int(cpu["logical_index"]) % 64)
        if len(masks_by_group) != 1:
            # WHY: SetProcessAffinityMask is single-group only. On dual-socket
            # or >64-logical-CPU systems the chosen CPU set may span multiple
            # processor groups; in that case CPU Sets are the only path and
            # there is no per-process affinity fallback. Surface this once in
            # the log AND in the capability report so the operator understands
            # why isolation is skipped on those PIDs. _log_once avoids per-call
            # churn from the dedup set when this fires on every WoW64 process.
            self._log_once(
                ("multi_group_affinity",),
                "[INFO] CPU partition spans multiple processor groups; per-process affinity fallback skipped for affected processes.",
            )
            self._note_capability(
                "Detected CPU partition spanning multiple processor groups; "
                "affinity fallback is unavailable for processes where CPU Sets API fails (e.g. WoW64)."
            )
            return False
        mask = next(iter(masks_by_group.values()))
        result = bool(kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(mask)))
        if not result:
            self._log_once(("affinity_fallback", ctypes.get_last_error()), f"[WARN] SetProcessAffinityMask failed: {self._last_error_text()}")
        return result

    def _apply_process_cpu_sets(self, handle, cpu_set_ids, reset_affinity_mask=True):
        if not cpu_set_ids:
            # Clearing CPU Sets is the cross-processor-group way to remove the
            # restriction. Do not also call SetProcessAffinityMask(system_mask):
            # that legacy API is primary-group scoped and can collapse a process
            # back to one group on >64-logical-CPU Windows systems.
            return self._set_process_default_cpu_sets(handle, [])
        # WHY: CPU Sets API does not work with 32-bit (WoW64) processes on 64-bit
        # Windows. SetProcessDefaultCpuSets silently fails for them. Detect this
        # and fall back to the affinity mask approach which works universally.
        if self._is_wow64_process(handle):
            self._log_once(("wow64_cpu_sets_skip",), "[INFO] Skipping CPU Sets for 32-bit process — using affinity fallback.")
            return self._apply_process_affinity_fallback(handle, cpu_set_ids)
        if cpu_set_ids and self._cpu_sets_by_id:
            if self._set_process_default_cpu_sets(handle, cpu_set_ids):
                return True
            return self._apply_process_affinity_fallback(handle, cpu_set_ids)
        return self._apply_process_affinity_fallback(handle, cpu_set_ids)

    def _get_thread_selected_cpu_sets(self, handle):
        required = wintypes.ULONG()
        kernel32.GetThreadSelectedCpuSets(handle, None, 0, ctypes.byref(required))
        if not required.value:
            return []
        buffer = (wintypes.ULONG * required.value)()
        if not kernel32.GetThreadSelectedCpuSets(handle, buffer, required.value, ctypes.byref(required)):
            return []
        return [int(buffer[index]) for index in range(required.value)]

    def _set_thread_selected_cpu_sets(self, handle, cpu_set_ids):
        if cpu_set_ids:
            buffer = (wintypes.ULONG * len(cpu_set_ids))(*[int(cpu_set_id) for cpu_set_id in cpu_set_ids])
            return bool(kernel32.SetThreadSelectedCpuSets(handle, buffer, len(cpu_set_ids)))
        return bool(kernel32.SetThreadSelectedCpuSets(handle, None, 0))

    def _get_thread_ideal_processor(self, handle):
        processor = PROCESSOR_NUMBER()
        if kernel32.GetThreadIdealProcessorEx(handle, ctypes.byref(processor)):
            return {"group": int(processor.Group), "number": int(processor.Number)}
        return None
