import subprocess
import re
import logging

logger = logging.getLogger(__name__)

class CBMCManager:
	UnwindStartVal = 2

	def __init__(self, configParam, sourceManagerParam):
		self.sourceManager = sourceManagerParam
		self.fileListParam = self.sourceManager.getTempFiles()
		self.config = configParam
		self.genericUnwindDepth = CBMCManager.UnwindStartVal
		self.specificUnwindDepth = {}
	
	def run(self):
		self.findUnwindDepth()
		self.exportDimacs()
	
	def exportDimacs(self):
		cmd = ["cbmc", "--verbosity", "4", "--function", self.config.function, "--dimacs", "--unwind", str(self.genericUnwindDepth)] + self.getSpecificUnwind()
		cmd.extend(self.config.cbmcArgs)
		inputSymbols = self.sourceManager.getInputSymbols()
		# NOTE(steuber): The following could be optimized with some fancy string algorithm probably...
		needles=[]
		for s in inputSymbols:
			needles.append("c "+self.config.function+"::"+s.name+"!0@1#1")
		
		if inputSymbols is None:
		 	raise Exception("No input variables for function found")
		for i in range(0,len(self.config.computeOutputs)):
			curCmd = cmd + ["--property", self.config.function+".assertion."+str(i+1)] + self.fileListParam
			logger.debug(" ".join(curCmd))
			curRun = subprocess.run(curCmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			if curRun.returncode != 0:
				logger.warning("CBMC CALL FAILED:")
				logger.warning(curRun.stderr.decode('ascii'))
			stdout = curRun.stdout.decode('ascii').split("\n")
			if stdout[0].strip().startswith("VERIFICATION SUCCESSFUL"):
				logger.info("Did not write file %s: State not reachable"%(self.config.computeOutputs[i][1]))
				continue
			inputLiterals = []
			for line in stdout[1:]:
				for n in needles:
					if line.startswith(n):
						inputLiterals.extend([
							x.strip() for x in line.split(" ")[2:] if x != "FALSE" and x != "TRUE"
						])
			with open(self.config.computeOutputs[i][1],"w") as outputF:
				print("c ind "+(" ".join(inputLiterals))+" 0",file=outputF)
				for line in stdout:
					print(line,file=outputF)
		
	
	def findUnwindDepth(self):
		if self.config.unwindDepth != -1:
			self.genericUnwindDepth = self.config.unwindDepth
			return
		baseCmd = ["cbmc", "--verbosity", "4", "--function", self.config.function, "--no-assertions", "--no-assumptions"]
		maxVal = self.genericUnwindDepth
		while True:
			runCmd = baseCmd + ["--unwind", str(self.genericUnwindDepth), "--unwinding-assertions"] + self.getSpecificUnwind() + self.fileListParam
			logger.debug(" ".join(runCmd))
			curRun = subprocess.run(runCmd, capture_output=True)
			if curRun.returncode == 0:
				# No more refinement necessary
				break
			if len(curRun.stderr)>0:
				# CBMC failed
				raise Exception("CBMC threw error: "+str(curRun.stderr))
			resultLines = curRun.stdout.decode('ascii').split("\n** Results:\n")[1].split("\n")
			nonBoundedLoop = False
			for l in resultLines:
				# Check for loop bound failures
				if len(l.strip()) == 0:
					# Only evaluate until empty line
					break
				reResult = re.match(r'\[([^\.]+).unwind.([^\.]+)\] .*: FAILURE$', l.strip())
				if reResult is not None:
					nonBoundedLoop=True
					loopIdent = reResult[1]+"."+reResult[2]
					if loopIdent in self.specificUnwindDepth:
						self.specificUnwindDepth[loopIdent]*=2
					else:
						self.specificUnwindDepth[loopIdent]=2*self.genericUnwindDepth
					if self.specificUnwindDepth[loopIdent]>maxVal:
						maxVal = self.specificUnwindDepth[loopIdent]
			if not nonBoundedLoop:
				self.genericUnwindDepth=maxVal
	
	def getSpecificUnwind(self):
		res = ["--unwindset"]
		param2=[]
		returnRes = False
		for loopIdent, val in self.specificUnwindDepth.items():
			param2.append(loopIdent+":"+str(val))
			returnRes = True
		res.append(",".join(param2))
		if returnRes:
			return res
		else:
			return []
			

	# Unwinding till bound assertion fulfilled:
	# First round: cbmc --function [xyz] --unwind 2 --unwinding-assertions --no-assertions --no-assumptions [files]
	# ith round: cbmc --function [xyz] --unwind [2^i*n] --unwindset [loopid0]:j ... --unwindset [loopidn]:k --unwinding-assertions --no-assertions --no-assumptions [files]