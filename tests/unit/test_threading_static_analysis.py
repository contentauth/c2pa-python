# Copyright 2023 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

# Unless required by applicable law or agreed to in writing,
# this software is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
# implied. See the LICENSE-MIT and LICENSE-APACHE files for the
# specific language governing permissions and limitations under
# each license.

import ast
import inspect
import unittest
import c2pa.c2pa as c2pa_module


class TestLockOrderStaticAnalysis(unittest.TestCase):
    """Static analysis over the source: no threads are spawned here.
    """

    def test_no_conflicting_lock_acquisition_order(self):
        """No two locks may be nested in opposite orders by different methods.

        Two methods nesting the same pair of locks in opposite order is a
        AB/BA deadlock shape: thread 1 holds A and waits for B while
        thread 2 holds B and waits for A.
        """
        tree = ast.parse(inspect.getsource(c2pa_module))

        # Every self._X = threading.Lock()/RLock()/Condition() assignment,
        # grouped by the class that owns it.
        lock_attrs_by_class = {}
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            found = set()
            for node in ast.walk(cls):
                if not (isinstance(node, ast.Assign)
                        and len(node.targets) == 1):
                    continue
                target = node.targets[0]
                if not (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"):
                    continue
                value = node.value
                if (isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Attribute)
                        and value.func.attr in
                        ("Lock", "RLock", "Condition")):
                    found.add(target.attr)
            if found:
                lock_attrs_by_class[cls.name] = found

        def lock_name_for_with(item):
            """The lock attribute a `with` item enters, or None."""
            ctx = item.context_expr
            # with self._fragment_lock:
            if (isinstance(ctx, ast.Attribute)
                    and isinstance(ctx.value, ast.Name)
                    and ctx.value.id == "self"
                    and any(ctx.attr in attrs
                            for attrs in lock_attrs_by_class.values())):
                return ctx.attr
            # with self._guarded_op(): returns _op_lock itself, and the
            # accessors return the lock they are named for.
            lock_by_method = {
                "_guarded_op": "_op_lock",
                "_live_op_lock": "_op_lock",
                "_live_teardown_lock": "_teardown_lock",
            }
            if (isinstance(ctx, ast.Call)
                    and isinstance(ctx.func, ast.Attribute)
                    and ctx.func.attr in lock_by_method
                    and isinstance(ctx.func.value, ast.Name)
                    and ctx.func.value.id == "self"):
                return lock_by_method[ctx.func.attr]
            return None

        def lock_name_for_acquire(node):
            """A lock taken with acquire() and released in a finally nests just
            as a `with` does, so the scan has to follow it or it silently stops
            seeing whole regions.
            """
            call = node.value if isinstance(node, ast.Expr) else node
            if isinstance(call, ast.UnaryOp) and isinstance(call.op, ast.Not):
                call = call.operand
            if not (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "acquire"):
                return None
            owner = call.func.value
            if (isinstance(owner, ast.Attribute)
                    and isinstance(owner.value, ast.Name)
                    and owner.value.id == "self"
                    and any(owner.attr in attrs
                            for attrs in lock_attrs_by_class.values())):
                return owner.attr
            return None

        def acquires_in_test(node):
            """Lock taken by `if not self._X.acquire(...)`-style guards."""
            if isinstance(node, ast.If):
                return lock_name_for_acquire(node.test)
            return None

        def orders_in(node, stack, pairs):
            """Record (outer, inner) for every nesting this node contains."""
            if isinstance(node, (ast.With, ast.AsyncWith)):
                names = [n for n in (lock_name_for_with(i)
                                     for i in node.items) if n]
                for name in names:
                    if stack:
                        pairs.add((stack[-1], name))
                    stack.append(name)
                for child in node.body:
                    orders_in(child, stack, pairs)
                for _ in names:
                    stack.pop()
                return
            # A statement list can open a lock partway through via acquire();
            # everything after it in that list is nested inside.
            for field, value in ast.iter_fields(node):
                if not isinstance(value, list):
                    continue
                held = []
                for child in value:
                    if not isinstance(child, ast.stmt):
                        continue
                    name = (lock_name_for_acquire(child)
                            or acquires_in_test(child))
                    if name:
                        if stack:
                            pairs.add((stack[-1], name))
                        stack.append(name)
                        held.append(name)
                        continue
                    orders_in(child, stack, pairs)
                for _ in held:
                    stack.pop()
            for child in ast.iter_child_nodes(node):
                if not isinstance(child, ast.stmt):
                    orders_in(child, stack, pairs)

        pairs_by_method = {}
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for method in cls.body:
                if not isinstance(method, (ast.FunctionDef,
                                           ast.AsyncFunctionDef)):
                    continue
                pairs = set()
                orders_in(method, [], pairs)
                if pairs:
                    pairs_by_method[(cls.name, method.name)] = pairs

        all_pairs = set().union(*pairs_by_method.values()) \
            if pairs_by_method else set()
        conflicts = []
        for (outer, inner) in all_pairs:
            # Each conflicting pair appears twice in all_pairs, once per direction.
            if outer >= inner or (inner, outer) not in all_pairs:
                continue
            forward = [k for k, v in pairs_by_method.items()
                      if (outer, inner) in v]
            backward = [k for k, v in pairs_by_method.items()
                       if (inner, outer) in v]
            conflicts.append(
                "{} nests {} inside {}, but {} nests {} inside {}".format(
                    forward[0], inner, outer, backward[0], outer, inner))

        self.assertGreater(len(pairs_by_method), 0, "scan found no nesting")
        self.assertEqual(conflicts, [], ", ".join(sorted(set(conflicts))))
