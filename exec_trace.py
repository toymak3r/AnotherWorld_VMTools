#!/usr/bin/env python
import sys

class CodeBlock():
  ''' A code block represents an address range in
      program memory. The range is specified by
      the self.start and self.end values.

      If a code block ends with a ret (return) instruction,
      then self.next_block will remain an empty list.

      Otherwise, it may have a single-element corresponding
      to a JMP instruction or a couple of values for each of
      the possible execution paths for a conditional branching
      instruction.
  '''

  def __init__(self, start, end, next_block=[]):
    self.start = start
    self.end = end
    self.subroutines = {}
    self.next_block = next_block

  def add_subroutine_call(self, instr_address, routine_address):
    self.subroutines[instr_address] = routine_address


ERROR = 0   # only critical messages
VERBOSE = 1 # informative non-error msgs to the user
DEBUG = 2   # debugging messages to the developer

class ExecTrace():
  """ ExecTrace is a generic class that implements an
      algorithm for mapping all reachable code-paths
      in a given binary.

      As a sub-product it can also emit:
      (1) a disassembly listing
      (2) a flow-chart
      (3) a map of code-regions versus data-regions

      This class must be inherited by a child-class
      providing a disasm_instruction method which
      (a) uses self.fetch() to read consecutive bytes from
      code memory
      (b) returns a string representing the disassembly of
      the current instruction
      (c) invokes the class methods listed below to declare
      the behaviour of the branching instructions.

      Instruction description methods:
        * subroutine(address)
           Declares that the current instruction
           invokes a subroutine at <address>

        * return_from_subroutine()
           Declares that the current instruction
           terminates the execution of a subroutine
           and jumps back to the code that originally
           invoked the subroutine.

        * conditional_branch(address)
           Declares that the current instruction
           is a conditional branch that may
           jump to <address>

        * unconditional_jump(address)
           Declares that the current instruction
           is an unconditional jump to <address>

        * illegal_instruction(opcode)
           Declares that the current instruction
           with operation code <opcode> could not
           be parsed as a valid known instruction.
  """
  def __init__(self, romfile, rombank=0, loglevel=ERROR):
    self.loglevel = loglevel
    self.rombank = rombank
    self.rom = open(romfile, "rb").read()
    self.visited_ranges = []
    self.pending_entry_points = []
    self.current_entry_point = None
    self.PC = None
    self.disasm = {}

### Public method to start the binary code interpretation ###
  def run(self, entry_point=0x0000):
    self.current_entry_point = entry_point
    self.PC = entry_point
    while self.PC is not None:
      address = self.PC
      opcode = self.fetch()
      if opcode != -1:
        self.disasm[address] = self.disasm_instruction(opcode)

### Methods for declaring the behaviour of branching instructions ###
  def subroutine(self, address):
    self.add_range(start=self.current_entry_point,
                   end=self.PC-1,
                   exit=[self.PC, address])
    self.schedule_entry_point(self.PC)
    self.schedule_entry_point(address)

    self.log(VERBOSE, "CALL SUBROUTINE ({})".format(hex(address)))
    self.log_status()
    self.restart_from_another_entry_point()

  def return_from_subroutine(self):
    self.add_range(start=self.current_entry_point,
                   end=self.PC-1,
                   exit=[])
    self.log(VERBOSE, "RETURN FROM SUBROUTINE")
    self.log_status()
    self.restart_from_another_entry_point()

  def conditional_branch(self, address):
    self.log(VERBOSE, "CONDITIONAL BRANCH to {}".format(hex(address)))
    self.branch(address, conditional=True)

  def unconditional_jump(self, address):
    self.log(VERBOSE, "UNCONDITIONAL JUMP to {}".format(hex(address)))
    self.branch(address, conditional=False)

  def branch(self, address, conditional):
    if address > self.current_entry_point and address < self.PC:
      self.add_range(start=self.current_entry_point,
                     end=address-1,
                     exit=[address])
      self.add_range(start=address,
                     end=self.PC-1,
                     exit=[self.PC, address])
      if conditional:
        self.schedule_entry_point(self.PC)
    else:
      self.add_range(start=self.current_entry_point,
                     end=self.PC-1,
                     exit=[self.PC, address])
      if conditional:
        self.schedule_entry_point(self.PC)
      self.schedule_entry_point(address)

    self.log_ranges()
    self.restart_from_another_entry_point()

  def illegal_instruction(self, opcode):
    self.add_range(start=self.current_entry_point,
                   end=self.PC-1,
                   exit=["Illegal Opcode: {}".format(hex(opcode))])
    self.log(ERROR, "[{}] ILLEGAL: {}".format(hex(self.PC-1), hex(opcode)))
    sys.exit(-1)

### Private methods for computing the code-execution graph structure ###
  def already_visited(self, address):
    if self.PC is not None:
      if address >= self.current_entry_point and address < self.PC:
        self.log(DEBUG, "RECENTLY: (PC={} address={})".format(hex(self.PC), hex(address)))
        return True

    for codeblock in self.visited_ranges:
      if address >= codeblock.start and address <= codeblock.end:
        self.log(DEBUG, "ALREADY VISITED: {}".format(hex(address)))
        if address > codeblock.start:
          # split the block into two:
          new_block = CodeBlock(start=codeblock.start,
                                end=address-1,
                                next_block=[address])
          codeblock.start = address
          # and also split ownership of subroutine calls:
          for instr_addr, call_addr in codeblock.subroutines.items():
            if instr_addr < address:
              new_block.add_subroutine_call(instr_addr, call_addr)
              del codeblock.subroutines[instr_addr]
          self.visited_ranges.append(new_block)
        return True

    # otherwise:
    return False

  def restart_from_another_entry_point(self):
    if len(self.pending_entry_points) == 0:
      self.PC = None  # This will finish the crawling
    else:
      address = self.pending_entry_points.pop()
      self.current_entry_point = address
      self.PC = address
      self.log(VERBOSE, "Restarting from: {}".format(hex(address)))

  def add_range(self, start, end, exit=None):
    if end < start:
      self.add_range(end, start, exit)
      return

    self.log(DEBUG, "=== New Range: start: {}  end: {} ===".format(hex(start), hex(end)))
    block = CodeBlock(start, end, exit)
    self.visited_ranges.append(block)

  def schedule_entry_point(self, address):
    if self.already_visited(address):
      return

    if address not in self.pending_entry_points:
      self.pending_entry_points.append(address)
      self.log(VERBOSE, "SCHEDULING: {}".format(hex(address)))
      self.log_status()

  def increment_PC(self):
    if self.already_visited(self.PC):
      self.log(VERBOSE, "ALREADY BEEN AT {}!".format(hex(self.PC)))
      self.log(DEBUG, "pending_entry_points: {}".format(self.pending_entry_points))
      self.add_range(start=self.current_entry_point,
                     end=self.PC-1,
                     exit=[self.PC])
      self.restart_from_another_entry_point()
      return -1
    else:
      self.PC += 1

  def fetch(self):
    value = self.rom[self.rombank + self.PC]
    self.log(DEBUG, f"Fetch at {hex(self.PC)}: {hex(value)}")
    if self.increment_PC() == -1:
      return -1
    return value

####### LOGGING #######
  def log(self, loglevel, msg):
    if self.loglevel >= loglevel:
      print(msg)

  def log_status(self):
    self.log(VERBOSE, "Pending: {}".format(map(hex, self.pending_entry_points)))

  def log_ranges(self):
    results = []
    for codeblock in sorted(self.visited_ranges, key=lambda cb: cb.start):
      results.append("[start: {}, end: {}]".format(hex(codeblock.start),
                                                   hex(codeblock.end)))
    self.log(DEBUG, "ranges:\n  " + "\n  ".join(results) + "\n")
#######################

  def print_grouped_ranges(self):
    results = []
    grouped = self.get_grouped_ranges()
    for codeblock in grouped:
      results.append("[start: {}, end: {}]".format(hex(codeblock[0]),
                                                   hex(codeblock[1])))
    print ("code ranges:\n  " + "\n  ".join(results) + "\n")

  def get_grouped_ranges(self):
    grouped = []
    current = None
    for codeblock in sorted(self.visited_ranges, key=lambda cb: cb.start):
      if current == None:
        current = [codeblock.start, codeblock.end]
        continue

      # FIX-ME: There's something bad going on here!!!
      if codeblock.start == current[1] or \
         codeblock.start == (current[1] + 1):
        current[1] = codeblock.end
        continue
#      print (">>> codeblock.start: {} current[1]: {}\n".format(hex(codeblock.start),
#                                                               hex(current[1])))
      grouped.append(current)
      current = [codeblock.start, codeblock.end]
      return grouped

  def save_disassembly_listing(self, filename="output.asm"):
    asm = open(filename, "w")
    asm.write(self.output_disasm_headers())

    next_addr = 0
    for codeblock in sorted(self.visited_ranges, key=lambda cb: cb.start):
      if codeblock.start < next_addr:
        # Skip repeated blocks!
        # something wrong happened here
        # I once saw a single byte range "LABEL_25D8: break" showing up twice here...
        continue

      if codeblock.start > next_addr:
        indent = "LABEL_%04X: " % next_addr
        data = []
        for addr in range(next_addr, codeblock.start):
          data.append(f"0x{self.rom[self.rombank + addr]:02X}")
          if len(data) == 8:
            asm.write(f"{indent}db {', '.join(data)}\n")
            indent = "            "
            data = []
        if len(data) > 0:
          asm.write(f"{indent}db {', '.join(data)}\n")

      address = codeblock.start
      indent = "LABEL_%04X: " % address
      for address in range(codeblock.start, codeblock.end+1):
        if address in self.disasm:
          asm.write(f"{indent}{self.disasm[address]}\n")
          indent = "            "
      next_addr = codeblock.end + 1
    asm.close()

def generate_graph():
  def block_name(block):
    return "{}-{}".format(hex(block.start), hex(block.end))

  import pydotplus
  graph = pydotplus.graphviz.Graph(graph_name='Code Execution Graph',
			   graph_type='digraph',
			   strict=False,
			   suppress_disconnected=False)
  graph_dict = {}
  for block in self.visited_ranges:
    node = pydotplus.graphviz.Node(block_name(block))
    graph.add_node(node)
    graph_dict[block.start] = node

  for block in self.visited_ranges:
    for nb in block.next_block:
      if nb is str:
        print (nb)  # this must be an illegal instruction
      else:
        if nb in graph_dict.keys():
          edge = pydotplus.graphviz.Edge(graph_dict[block.start], graph_dict[nb])
          graph.add_edge(edge)
        else:
          print (f"Missing codeblock: {hex(nb)}")

  open("output.gv", "w").write(graph.to_string())

  #from graphviz import Digraph
  #dot = Digraph(comment='Code Execution Graph')
  #dot.render('test-output/round-table.gv', view=True)

