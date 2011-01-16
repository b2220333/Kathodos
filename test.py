import direct.directbase.DirectStart
from panda3d.core import *
from pandac.PandaModules import *
from direct.gui.OnscreenText import OnscreenText
from direct.actor.Actor import Actor
from direct.showbase.DirectObject import * #DirectObject, globalClock
from joystick import *
import sys
import pickle
# import random, sys, os, math
#from pandac.PandaModules import Thread as PandaThread

import pyhnet.hnet as hnet
#import threading

import time
#from direct.stdpy import pandaThreads

#TODO fix networking handler

def MyActor(*args, **kwargs):
  x = ActorNode(*args, **kwargs)
  x.setTag("actor", pickle.dumps(None))
  return x

class PlayerIntent:
  def __init__(self, playerId, fireOn = False, thrusters = Vec3(0.0, 0.0, 0.0), rotThrusters = Vec3(0.0, 0.0, 0.0)):
      self.playerId = playerId
      self.fireOn = fireOn
      self.thrusters = Vec3(thrusters)
      self.rotThrusters = Vec3(rotThrusters)
      
  def __eq__(self, other):
      return self.playerId == other.playerId and self.fireOn == other.fireOn and self.thrusters == other.thrusters and self.rotThrusters == other.rotThrusters
    
  def __add__(self, other):
      return PlayerIntent( self.playerId
                         , self.fireOn or other.fireOn
                         , Vec3(tuple([max((-1.0, min((1.0, x)))) for x in self.thrusters + other.thrusters]))
                         , Vec3(tuple([max((-1.0, min((1.0, x)))) for x in self.rotThrusters + other.rotThrusters]))
                         )
  
  #these functions are helper functions 
  # for event handling
  def setFireOn(self, a): self.fireOn = a
  
  def setForwardThruster(self, x):  self.thrusters[1] = -x
  def setLeftThruster(self, x):     self.thrusters[0] = x
  def setUpThruster(self, x):       self.thrusters[2] = x      
  
  def setHeadingThruster(self, x): self.rotThrusters[0] = x  #aka Yaw
  def setPitchThruster(self, x):   self.rotThrusters[1] = x
  def setRollThruster(self, x):    self.rotThrusters[2] = x
  
  # call processIntent on player object
  def process(self, world):
      world.players[self.playerId].intent = self
      #world.players[self.playerId].processIntent(self)
  

def clampVector(v, maxLength):
  if v.length() > maxLength:
      v.normalize()
      return v * maxLength
  else:
      return v
    
def neg(x):
    return -x
    
def compose(f, g):
    def fg(x):
        return f(g(x))
    return fg
    
#TODO we need some for of error handling here
class NetworkingHandler(hnet.HNetHandler):
    def onInit(self):
        self.incoming = hnet.Queue()
        self.outgoing = hnet.Queue()
        self.playerId = None
        self.gameJoined = hnet.Event()
        self.gameName = "MyGame"
        self.obj = None
        
    def runConnection(self):
        reply = self.sendAndWait('Hello')
        self.obj = reply.proxy()
        self.playerId = self.obj.joinGame(self.gameName, "Job")
        self.gameJoined.set()
        self.done.wait()                
            
    def sendGamePacket(self, stuff):
        self.obj.sendGamePacket(self.gameName, stuff)
        
    def onRecv(self, packet):
        self.incoming.put(packet.msg())
        
    def onError(self, exc_type, value, traceback): 
      raise
      #TODO do something more usefull/gracefull here
      
      

class StateSaver:
  accessors = []
  nested = {}
  def __init__(self, obj = None):
    self.state = {}
    if obj != None:
      self.save(obj)
    
  def save(self, obj):
    for name, C in self.nested.items():
      self.state['#' + name] = C(getattr(obj, name)())
    for name in self.accessors:
      self.state[name] = getattr(obj, "get" + name)()
    return self
  
  def restore(self, obj):
    for name, C in self.nested.items():
      self.state['#' + name].restore(getattr(obj, name)())
    for name in self.accessors:
      getattr(obj, "set" + name)(self.state[name])
    
      
class PhysicsState(StateSaver):
  accessors = [ 'Name'
              , 'Mass'
              , 'Active'
              , 'LastPosition'
              , 'Position'
              , 'Velocity'
              , 'TerminalVelocity'
              , 'Oriented'
              , 'Orientation'
              , 'Rotation'
              ]
  
class ActorState(StateSaver):
  accessors = [ 'ContactVector' ]
  nested = {'getPhysicsObject' : PhysicsState }

        
class Player:
    def __init__(self, playerId, world, name, pos):
        self.world = world
        self.playerId = playerId
        nodePath = NodePath(PandaNode("playerShipNode"))
        nodePath.setTag("player", str(playerId))
        nodePath.reparentTo(world.root)
        actorNode = MyActor("playerShip-physics")
        actorNode.getPhysicsObject().setMass(2000.0) # two metric tons
        #actorNode.getPhysicsObject().setTerminalVelocity(150.0)
        
        #TODO handle this more neatly somehow
        self.world.physicsMgr.attachPhysicalNode(actorNode)
        
        actorNodePath = nodePath.attachNewNode(actorNode)
        actorNodePath.setPos(pos)
        
        modelNode = loader.loadModel("media/models/Fighter")
        modelNode.reparentTo(actorNodePath)
        modelNode.setScale(0.1)
        modelNode.setHpr(180.0, 0.0, 0.0)
        
        
        boundingSphere = CollisionNode('player-' + name + '-bounds')
        boundingSphere.addSolid(CollisionSphere(0, 0, 0, 2))
        collideNode = actorNodePath.attachNewNode(boundingSphere)
        collideNode.setTag("collides", "handle")
        #collideNode.show()
        
        self.world.cHandler.addCollider(collideNode, actorNodePath)
        self.world.cTrav.addCollider(collideNode, self.world.cHandler)
        
        self.nodePath = nodePath
        self.actorNode = actorNode
        self.actorNodePath = actorNodePath
        self.modelNode = modelNode
        self.collideNode = collideNode
        self.laserCool = 0.0
        self.intent = PlayerIntent(self.playerId)
        
        
        
    #def saveState(self):
    #  return 
    
    #TODO add a filter for multiple intent packets for a single player
    def processIntent(self):
        if self.intent.fireOn:
            if self.world.clock.getFrameCount() >= self.laserCool:
                self.world.createLaserProjectile(self)
                self.laserCool = self.world.clock.getFrameCount() + self.world.time2frames(0.4)

        lcs = self.actorNodePath.getMat()

        currentVelocity = self.actorNode.getPhysicsObject().getVelocity()
        desiredVelocity = Vec3(lcs.xformVec(self.intent.thrusters)) * 80.0
        deltaVel = desiredVelocity - currentVelocity
        #TODO, there are a lot of arbitrary numbers here,
        #  we should group them mostly in one place and label their units
        maxAccel = 10.0
        
        thrust = clampVector(deltaVel * 0.1, maxAccel)
        self.actorNode.getPhysicsObject().addImpulse(thrust)
                    
        h, p, r = self.intent.rotThrusters * 1.5
        self.actorNode.getPhysicsObject().addLocalTorque(LRotationf(h, p, r)*0.1)
        
handler = None

class World(DirectObject):

    def handleLaserHitLevel(self, entry):
        laser = entry.getFromNodePath()
        laser.removeNode()
        self.laserHitWall.play()
        #print "hit level"
    def handleLaserHitShip(self, entry):
        laser = entry.getFromNodePath()
        laser.removeNode()
        self.laserHitPlayer.play()
        #print "hit ship"
      
    def time2frames(self, t):
        return int(round(t/self.clock.getDt()))
        
    def doSaves(self, a):
      #asdf = ActorNode(PandaNode("test"))
      if self.lastSave == None:
        self.lastSave = self.save()
    def doRestores(self, a):
      if self.lastSave != None:
        self.restore(self.lastSave)
        self.lastSave = None
      
    def save(self):
      for actor in self.root.findAllMatches("**/=actor"):
        actor.setTag("actor", pickle.dumps(ActorState(actor.node())))
      return pickle.dumps(self.root)
        
    def restore(self, data):
      #clear colliders
      self.cHandler.clearColliders()
      self.cTrav.clearColliders()
      
      self.physicsMgr.clearPhysicals()
      
      #clear any old lights
      for light in self.root.findAllMatches("**/*Light"):
        self.root.clearLight(light)
      
      
      self.root.removeNode()
      
      self.root = pickle.loads(data)
      self.root.reparentTo(self.render)
      
      #restore ActorNodes
      for actor in self.root.findAllMatches("**/=actor"):
        actorState = pickle.loads(actor.getTag("actor"))
        newActor = MyActor(actor.getName())
        newActor.replaceNode(actor.node())
        actorState.restore(newActor)

      #restore camera
      playerShipActorNodePath = self.root.find("**/=player=%i/playerShip-physics" % (self.playerId))
      base.camera.reparentTo(playerShipActorNodePath)
      base.camera.setPos(Vec3(0,20,5))
      base.camera.lookAt(playerShipActorNodePath)
          
      #restore lights
      #TODO use a better search key here
      for light in self.root.findAllMatches("**/*Light"):
        self.root.setLight(light)
      
      
      #restore collision traversers
      for collider in self.root.findAllMatches("**/=collides"):
        self.physicsMgr.attachPhysicalNode(collider.getParent().node())
        if collider.getTag("collides") == "handle":
          self.cHandler.addCollider(collider, collider.getParent())
          self.cTrav.addCollider(collider, self.cHandler)
        else:
          self.cTrav.addCollider(collider, self.pHandler)
      
    def addPlayer(self, playerId, name):
        playerShip = Player(playerId, self, name, Vec3(0,-40,0))
        self.players[playerId] = playerShip
        print "New Player!", playerId
        if playerId == self.playerId:
          base.camera.reparentTo(playerShip.actorNodePath)
          base.camera.setPos(Vec3(0,20,5))
          base.camera.lookAt(playerShip.actorNodePath)
          
    def createLaserProjectile(self, player):
        laser = PandaNode("laserProjectile")
        self.laserSound.play()
        velocity = Vec3(0.0, -120.0, 0.0) #-120
        nodePath = player.actorNodePath.attachNewNode(laser)

        actorNode = MyActor("projectile-laser")
        actorNode.getPhysicsObject().setVelocity(velocity)
        
        #actorNode.setPos(0.0, -3.0, 0.0)
        
        self.physicsMgr.attachPhysicalNode(actorNode)
        
        actorNodePath = nodePath.attachNewNode(actorNode)
        actorNodePath.setPos(0.0, -3.0, 0.0)
        
        modelNode = NodePath(PandaNode("laserNode"))
        modelNode.reparentTo(actorNodePath)
        #modelNode.setPos(0.0, -2.0, 0.0)
          
        #pointA = Point3(0.0, 0.0, 0.0)
        #pointB = Point3(0.0, -1.0, 0.0)
        boundingObject = CollisionNode('laser-bounds')
        #boundingObject.addSolid(CollisionSegment(pointA, pointB))
        boundingObject.addSolid(CollisionSphere(0.0, 0.0, 0.0, 0.1))
        boundingObject.setIntoCollideMask(0)
        collideNode = actorNodePath.attachNewNode(boundingObject)
        collideNode.show()
        collideNode.setTag("collides", "trav")
        
        #self.cHandler.addCollider(collideNode, actorNodePath)
        #self.cTrav.addCollider(collideNode, self.cHandler)
        
        self.cTrav.addCollider(collideNode, self.pHandler)
        
        nodePath.wrtReparentTo(self.root)
        #def printGraph(node):
        #  print node
        #  print node.node().getClassType()
        #  for child in node.getChildren():
        #    printGraph(child)
        #printGraph(self.root)
        #self.root.ls()
        #test = pickle.dumps(render)
        #test = pickle.loads(test)
        #print printGraph(test)
        #test = pickle.dumps(actorNode.getPhysicsObject().getVelocity())
        #b = pickle.loads(test)
        #print b
        #myworld = pickle.loads(sceneGraph)
        #render.removeChildren()
        #render.reparentTo(pickle.loads(sceneGraph))
        #self.root.removeNode()
        
      
    def __init__(self, render):
        global handler
        self.render = render
        self.root = render.attachNewNode(PandaNode("root"))
        self.keyMap = {"left":0, "right":0, "forward":0, "cam-left":0, "cam-right":0}
        self.axisData = Vec3(0.0,0.0,0.0)
        base.win.setClearColor(Vec4(0,0,0,1))
        
        self.multiplayer = False
        self.frameQueue = []
        self.frames = {}
        
        self.lastSave = None
        
        if self.multiplayer:
          #TODO, this is kinda a lame setup, no error handling, etc...
          self.networkHandler = NetworkingHandler(hnet.connectTCP('localhost', 30131))
          self.networkHandler.run()
          self.networkHandler.gameJoined.wait(1.0)
          handler = self.networkHandler
          self.playerId = self.networkHandler.playerId
        else:
          self.playerId = 0
          
          

        self.players = {}
        base.disableMouse()
        self.physicsMgr = PhysicsManager()
        
        #base.enableParticles()
        self.physicsMgr.attachLinearIntegrator(LinearEulerIntegrator())
        self.physicsMgr.attachAngularIntegrator(AngularEulerIntegrator()) # add angular integrator to the physics manager (for rotational physics)
        
        self.environ = loader.loadModel("levels/minerva")
        self.environ.reparentTo(self.root)

        self.cHandler = PhysicsCollisionHandler()

        self.cTrav = CollisionTraverser()
        self.cTrav.setRespectPrevTransform( True )
        
        #self.cTrav.showCollisions(render)
        
        self.pHandler = CollisionHandlerEvent()
        self.pHandler.addInPattern('%fn-into-%in')
        self.accept('laser-bounds-into-player-player1-bounds', self.handleLaserHitShip)
        self.accept('laser-bounds-into-level', self.handleLaserHitLevel)
        
        self.laserSound = base.loader.loadSfx("media/sound/laser02.wav")
        self.laserHitWall = base.loader.loadSfx("media/sound/explode1.wav")
        self.laserHitPlayer = base.loader.loadSfx("media/sound/shit01.wav")
        
        
        
        if not self.multiplayer:
          self.addPlayer(self.playerId, "player1")

        self.joystickIntent = PlayerIntent(self.playerId)
        self.keyboardIntent = PlayerIntent(self.playerId)

        self.joy = JoystickHandler()

        def addControlKey(keyName, f):
            self.accept(keyName, f, [True])
            self.accept(keyName + "-up", f, [False])
          
        def addKeyAxis(keyA, keyB, f):
            def magic(a, b, x = [0.0, 0.0]): # this function keeps the state of x around
                if a != None: x[0] = a
                if b != None: x[1] = b
                f(sum(x))
            self.accept(keyA, magic, [1.0, None])
            self.accept(keyA + "-up", magic, [0.0, None])
            self.accept(keyB, magic, [None, -1.0])
            self.accept(keyB + "-up", magic, [None, 0.0])

        def addHatAxis(hatName, setLeftRight, setUpDown, f = lambda x: x, g = lambda x: x):
            def h((leftRight, upDown)):
                setLeftRight(f(leftRight))
                setUpDown(g(upDown))
            self.accept(hatName, h)

        def addAxis(joyAxisName, f, g = lambda x: x):
            self.accept(joyAxisName, compose(f, g))

          
        self.accept("escape", sys.exit)
        
        addKeyAxis("a", "d", self.keyboardIntent.setLeftThruster)
        addKeyAxis("w", "s", self.keyboardIntent.setUpThruster)
        addKeyAxis("t", "enter", self.keyboardIntent.setForwardThruster)
    
        addKeyAxis("4", "6", self.keyboardIntent.setHeadingThruster)
        addKeyAxis("8", "5", self.keyboardIntent.setPitchThruster)
        addKeyAxis("7", "9", self.keyboardIntent.setRollThruster)
        addControlKey("space", self.keyboardIntent.setFireOn)
        addControlKey("j", self.doSaves)
        addControlKey("k", self.doRestores)

        # Hard coded joystick controls (Ron's config)
        #addKeyAxis("joystick0-button7", "joystick0-button6", self.keyboardIntent.setForwardThruster)
        #addKeyAxis("joystick0-button2", "joystick0-button1", self.keyboardIntent.setHeadingThruster)
        #addKeyAxis("joystick0-button3", "joystick0-button0", self.keyboardIntent.setPitchThruster)
        
        addAxis("joystick0-axis0", self.joystickIntent.setHeadingThruster, neg)
        addAxis("joystick0-axis1", self.joystickIntent.setPitchThruster, neg)
        addAxis("joystick0-axis2", self.joystickIntent.setForwardThruster, neg)
        addHatAxis("joystick0-hat0", self.joystickIntent.setLeftThruster, self.joystickIntent.setUpThruster, neg)
        addControlKey("joystick0-button0", self.joystickIntent.setFireOn)
        

        taskMgr.add(self.doPhys, "physFrameTask", sort = 30)
        if self.multiplayer:
            taskMgr.add(self.doNetworking, "networking")
        
        print taskMgr

        # Create some lighting
        ambientLight = AmbientLight("ambientLight")
        ambientLight.setColor(Vec4(.3, .3, .3, 1))
        directionalLight = DirectionalLight("directionalLight")
        directionalLight.setDirection(Vec3(-5, -5, -5))
        directionalLight.setColor(Vec4(1, 1, 1, 1))
        directionalLight.setSpecularColor(Vec4(1, 1, 1, 1))
        self.root.setLight(self.root.attachNewNode(ambientLight))
        self.root.setLight(self.root.attachNewNode(directionalLight))
        #base.cTrav = self.cTrav
        self.clock = ClockObject()
        self.clock.setMode(self.clock.MNonRealTime)
        self.clock.setFrameRate(60.0)
        base.setFrameRateMeter(True)
        

    def doNetworking(self, task):
        while not self.networkHandler.incoming.empty():
          playerId, frame, (tag, data) = self.networkHandler.incoming.get_nowait()
          if tag == "PlayerUpdate":
              intent = pickle.loads(data)
              intent.playerId = playerId # just to make sure the other client isn't lieing to us
              if frame not in self.frames:
                  self.frames[frame] = []
              self.frames[frame].append(intent)
          elif tag == "PlayerJoined":
              self.addPlayer(playerId, data)
          elif tag == "NewFrame":
              lastFrame = frame -1
              if lastFrame in self.frames:
                  self.frameQueue.append(self.frames[lastFrame])
                  del self.frames[lastFrame]
              else:
                  self.frameQueue.append([])
        return task.cont
      
    def doPhys(self, task):
        currentIntent = self.keyboardIntent + self.joystickIntent
        if self.players[self.playerId].intent != currentIntent:
          if self.multiplayer:
            self.networkHandler.sendGamePacket(("PlayerUpdate", pickle.dumps(currentIntent)))
          else:
            self.frameQueue.append([currentIntent])
        else:
          if not self.multiplayer:
            self.frameQueue.append([])
          
        #TODO add something here so that we leave an extra frame of delay that we can use
        #  when a frame is delayed from the server (actually the way I'm doing the frames like this is kinda bad)
        while len(self.frameQueue) > 0:
            self.processFrame(self.frameQueue.pop(0))
        return task.cont
      
    def processFrame(self, frameEvents):
        for event in frameEvents:
            event.process(self)
        for player in self.players.values():
            player.processIntent()
        self.physicsMgr.doPhysics(self.clock.getDt())
        self.cTrav.traverse(self.render)
        self.clock.tick()

try:        
  w = World(render)
  run()
finally:
  if handler:
    handler.close()


