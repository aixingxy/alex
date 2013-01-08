#!/usr/bin/env python
# -*- coding: utf8 -*-

"""Factor representation for computing with discrete variables."""

import numpy as np
import operator

from collections import defaultdict


class DiscreteFactor(object):
    """Factor representation with basic operations."""

    def _factor_table_length(self, cardinalities):
        """Length of the factor table (number of assignments)."""
        length = reduce(operator.mul, cardinalities.values())
        return length

    def _compute_strides(self, variables, cardinalities, factor_length):
        """Strides for variables for given factor table."""
        strides = defaultdict(int)
        last_stride = factor_length
        for variable in variables:
            last_stride = last_stride / cardinalities[variable]
            strides[variable] = last_stride
        return strides

    def _get_index_from_assignment(self, assignment):
        """Transform variables assignment to index into factor table."""
        index = 0
        for var, assignment_i in zip(self.variables, assignment):
            index += (self.strides[var] *
                      self.translation_table[var][assignment_i])
        return index

    def _get_assignment_from_index(self, index):
        """Assignment in factor table at given index."""
        assignment = []
        for var in self.variables:
            assignment.append(index / self.strides[var])
            index %= self.strides[var]
        return tuple(assignment)

    def _create_translation_table(self, variables_values):
        """Create translation from string values to numbers."""
        translation_table = {}
        for var in variables_values:
            translation_table[var] = {}
            for i, value in enumerate(variables_values[var]):
                translation_table[var][value] = i
        return translation_table

    def __init__(self, variables_dict, prob_table):
        self.variables = sorted(variables_dict.keys())
        self.variables_dict = variables_dict
        self.translation_table = self._create_translation_table(variables_dict)
        self.cardinalities = {var: len(variables_dict[var])
                              for var in self.variables}

        if isinstance(prob_table, np.ndarray):
            self.factor_table = prob_table
            self.factor_length = self.factor_table.size
        elif isinstance(prob_table, dict):
            self.factor_length = self._factor_table_length(self.cardinalities)
            self.factor_table = np.ndarray(self.factor_length, np.float32)

        self.strides = self._compute_strides(self.variables,
                                             self.cardinalities,
                                             self.factor_length)

        self.unobserved_factor_table = self.factor_table

        if isinstance(prob_table, dict):
            for assignment, value in prob_table.iteritems():
                self.factor_table[
                    self._get_index_from_assignment(assignment)] = value

    def __str__(self):
        ret = ""
        num_columns = len(self.variables) + 1
        column_len = 79 / num_columns
        format_str = "{:^%d}" % column_len

        ret += 79 * "-" + "\n"

        for var in self.variables:
            ret += format_str.format(var)
        ret += format_str.format("Value") + "\n"
        ret += 79 * "-" + "\n"
        for i in range(len(self.factor_table)):
            for assignment in self._get_assignment_from_index(i):
                ret += format_str.format(assignment)
            ret += format_str.format(self.factor_table[i]) + "\n"
        ret += 79 * "-" + "\n"
        return ret

    def rename_variables(self, new_variables):
        """Rename variables."""
        for var in self.variables_dict:
            if var in new_variables:
                self.variables_dict[new_variables[var]] = (
                    self.variables_dict.pop(var))
                self.strides[new_variables[var]] = self.strides.pop(var)
                self.cardinalities[new_variables[var]] = (
                    self.cardinalities.pop(var))
        self.variables = self.variables_dict.keys()
        self.translation_table = self._create_translation_table(
            self.variables_dict)

    def marginalize(self, variables):
        """Marginalize the factor."""
        # Assignment counter
        assignment = defaultdict(int)
        # New dictionary containing only cardinalities for resulting variables.
        new_cardinalities = {x: self.cardinalities[x] for x in variables}
        # Length of the new factor table.
        new_factor_length = self._factor_table_length(new_cardinalities)
        # The new factor table.
        new_factor_table = np.zeros(new_factor_length, np.float32)
        # Strides for resulting variables in the new factor table.
        new_strides = self._compute_strides(variables,
                                            self.cardinalities,
                                            new_factor_length)
        # Index into the new factor table.
        index = 0

        # Iterate over every element in the old factor table and add them to
        # the correct element in the new factor table.
        for i in range(self.factor_length):
            new_factor_table[index] += self.factor_table[i]

            # Update the assignment and indexes.
            for var in variables:
                # The assignment of variable var changed, so we must add its
                # stride to the index.
                if (i+1) % self.strides[var] == 0:
                    assignment[var] += 1
                    index += new_strides[var]
                # The assignment of variable var overflowed to 0, we must
                # subtract the cardinality from index.
                if assignment[var] == self.cardinalities[var]:
                    assignment[var] = 0
                    index -= (self.cardinalities[var] *
                              new_strides[var])

        # Return new factor with marginalized variables.
        new_variables_dict = {v: self.variables_dict[v] for v in variables}
        return DiscreteFactor(new_variables_dict, new_factor_table)

    def observed(self, assignment):
        """Set observation."""
        if assignment is not None:
            self.factor_table = np.zeros(self.factor_length)
            self.factor_table[
                self._get_index_from_assignment(assignment)] = 1.0
        else:
            self.factor_table = self.unobserved_factor_table

    def __getitem__(self, assignment):
        index = self._get_index_from_assignment(assignment)
        return self.factor_table[index]

    def _multiply_same(self, other_factor):
        """Multiply two factors with same variables."""
        return DiscreteFactor(self.variables_dict,
                              self.factor_table * other_factor.factor_table)

    def _multiply_different(self, other_factor):
        """Multiply two factors with different variables."""
        # The new set of variables will contain variables from both factors.
        new_variables = sorted(
            set(self.variables).union(other_factor.variables))
        # New cardinalities will contain cardinalities of all variables.
        new_cardinalities = self.cardinalities
        new_cardinalities.update(other_factor.cardinalities)
        # The new factor table will be larger, because it will contain more
        # variables.
        new_factor_length = self._factor_table_length(new_cardinalities)
        # The new factor table.
        new_factor_table = np.ndarray(new_factor_length, np.float32)

        # Assignment in new factor table.
        assignment = defaultdict(int)
        # Indexes into factor tables.
        index_self = 0
        index_other = 0
        reversed_variables = new_variables[::-1]

        for i in range(new_factor_length):
            # Multiply values from input factors to get new factor.
            new_factor_table[i] = (self.factor_table[index_self] *
                                   other_factor.factor_table[index_other])

            # Update the assignment and indexes.
            for var in reversed_variables:
                # Last variable has stride 1 and always changes it's value.
                assignment[var] += 1
                # The assignment of var overflowed to 0?
                if assignment[var] == new_cardinalities[var]:
                    assignment[var] = 0
                    # Move indexes in tables to correct assignment.
                    index_self -= ((new_cardinalities[var] - 1) *
                                   self.strides[var])
                    index_other -= ((new_cardinalities[var] - 1) *
                                    other_factor.strides[var])
                else:
                    # var is the last variable that changed.
                    index_self += self.strides[var]
                    index_other += other_factor.strides[var]
                    break

        new_variables_dict = dict(self.variables_dict)
        new_variables_dict.update(other_factor.variables_dict)

        return DiscreteFactor(new_variables_dict,
                              new_factor_table)

    def __mul__(self, other_factor):
        if self.variables == other_factor.variables:
            return self._multiply_same(other_factor)
        else:
            return self._multiply_different(other_factor)

    def _divide_same(self, other_factor):
        """Divide factor by other factor with same variables."""
        return DiscreteFactor(self.variables_dict,
                              self.factor_table / other_factor.factor_table)

    def _divide_different(self, other_factor):
        """Divide factor by other factor with less variables."""
        new_factor_table = np.empty_like(self.factor_table)
        assignment = defaultdict(int)
        index_other = 0
        reversed_variables = self.variables[::-1]

        for i in range(self.factor_length):
            if self.factor_table[i] == 0:
                new_factor_table[i] = 0
            else:
                new_factor_table[i] = (self.factor_table[i] /
                                       other_factor.factor_table[index_other])

            for var in reversed_variables:
                assignment[var] += 1
                if assignment[var] == self.cardinalities[var]:
                    assignment[var] = 0
                    index_other -= ((self.cardinalities[var] - 1) *
                                    other_factor.strides[var])
                else:
                    index_other += other_factor.strides[var]
                    break

        return DiscreteFactor(self.variables_dict,
                              new_factor_table)

    def __div__(self, other_factor):
        if not set(self.variables).issuperset(set(other_factor.variables)):
            raise ValueError(
                "The denominator is not a subset of the numerator.")

        if self.variables == other_factor.variables:
            return self._divide_same(other_factor)
        else:
            return self._divide_different(other_factor)